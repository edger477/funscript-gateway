"""OutputManager — 20 Hz evaluation loop that drives all configured outputs."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request

from funscript_gateway.app_state import AppState
from funscript_gateway.funscript.engine import FunscriptEngine, interpolate
from funscript_gateway.models import (
    FunscriptAxisInput,
    MediaConnectionState,
    OutputConfig,
    OutputInstance,
    RestimInput,
)
from funscript_gateway.outputs.tasmota import TasmotaDriver
from funscript_gateway.outputs.threshold import ThresholdSwitchProcessor
from funscript_gateway.outputs.mqtt import MqttDriver

logger = logging.getLogger(__name__)

_EVAL_INTERVAL_S = 0.050  # 20 Hz


class OutputManager:
    """Manages the lifecycle of all output drivers and runs the evaluation loop."""

    def __init__(self, app_state: AppState, engine: FunscriptEngine) -> None:
        self._app_state = app_state
        self._engine = engine
        self._running = False
        self._task: asyncio.Task | None = None
        self._mqtt_drivers: list[MqttDriver] = []
        self._was_connected: bool = False
        self._was_playing: bool = False

    async def start(self) -> None:
        self._running = True
        await self._setup_outputs()
        self._task = asyncio.ensure_future(self._evaluation_loop())

    async def stop(self) -> None:
        self._running = False
        await self._handle_disconnect()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        await self._disconnect_mqtt_drivers()

    async def reload_outputs(self) -> None:
        """Rebuild all output instances from the current config (called after UI changes)."""
        await self._disconnect_mqtt_drivers()
        await self._setup_outputs()
        self._app_state.outputs_updated.emit()

    async def _disconnect_mqtt_drivers(self) -> None:
        for driver in self._mqtt_drivers:
            try:
                await driver.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._mqtt_drivers.clear()

    async def _setup_outputs(self) -> None:
        """Instantiate all OutputInstance objects from app_state.config.outputs."""
        outputs: list[OutputInstance] = []
        for cfg in self._app_state.config.outputs:
            instance = await self._create_output_instance(cfg)
            if instance is not None:
                outputs.append(instance)
        self._app_state.outputs = outputs

    async def _create_output_instance(self, cfg: OutputConfig) -> OutputInstance | None:
        processor = ThresholdSwitchProcessor(cfg.threshold)
        driver = await self._create_driver(cfg)
        if driver is None:
            return None
        return OutputInstance(config=cfg, processor=processor, driver=driver)

    async def _create_driver(self, cfg: OutputConfig) -> object | None:
        match cfg.type:
            case "threshold_tasmota":
                return TasmotaDriver(cfg.tasmota)
            case "threshold_mqtt":
                driver = MqttDriver(cfg.mqtt)
                try:
                    await driver.connect()
                    self._mqtt_drivers.append(driver)
                    return driver
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Output '%s': MQTT connection failed (%s); "
                        "output will be inactive until reload.",
                        cfg.name, exc,
                    )
                    return None
            case _:
                logger.warning("Unknown output type '%s' for '%s'.", cfg.type, cfg.name)
                return None

    def _resolve_input(self, input_name: str):
        """Return the named input from app_state.inputs, or None."""
        for inp in self._app_state.inputs:
            if inp.name == input_name:
                return inp
        return None

    @staticmethod
    def _input_is_available(inp) -> bool:
        if not inp.enabled:
            return False
        if isinstance(inp, FunscriptAxisInput):
            # file_missing with default_value still counts as available
            return True
        if isinstance(inp, RestimInput):
            return not inp.is_error
        return True  # CalculatedInput always available when enabled

    async def _evaluation_loop(self) -> None:
        loop = asyncio.get_event_loop()
        while self._running:
            start = loop.time()

            player_state = self._app_state.player_state
            connection_state = player_state.connection_state
            is_connected = connection_state != MediaConnectionState.NOT_CONNECTED
            is_playing = connection_state == MediaConnectionState.CONNECTED_AND_PLAYING

            # Detect disconnect transition.
            if not is_connected and self._was_connected:
                await self._handle_disconnect()
                self._was_connected = False
            elif is_connected:
                self._was_connected = True

            # Detect play-start transition → restim autostart.
            if is_playing and not self._was_playing:
                await self._handle_restim_autostart()
            self._was_playing = is_playing

            if is_playing:
                self._engine.update_values(self._app_state.current_time_ms)

            for output in self._app_state.outputs:
                if not output.config.enabled:
                    continue
                if output.driver is None:
                    continue

                inp = self._resolve_input(output.config.input_name)

                if inp is None:
                    forced = self._handle_missing_input_behavior(output)
                    if forced is None:
                        continue
                    new_state = forced
                elif not self._input_is_available(inp):
                    forced = self._handle_missing_input_behavior(output)
                    if forced is None:
                        continue
                    new_state = forced
                elif isinstance(inp, FunscriptAxisInput):
                    # FunscriptAxisInput only drives output during playback
                    if is_playing:
                        new_state = output.processor.process(inp.current_value)
                        output.last_input_value = inp.current_value
                    else:
                        forced = self._handle_pause_behavior(output)
                        if forced is None:
                            continue
                        new_state = forced
                else:
                    # RestimInput / CalculatedInput: always active, independent of player state
                    new_state = output.processor.process(inp.current_value)
                    output.last_input_value = inp.current_value

                output.last_output_state = new_state

                try:
                    await output.driver.set_state(new_state)
                    output.consecutive_errors = 0
                    output.is_degraded = False
                except Exception as exc:  # noqa: BLE001
                    output.consecutive_errors += 1
                    if output.consecutive_errors >= 3:
                        output.is_degraded = True
                    logger.warning(
                        "Output '%s' driver error: %s", output.config.name, exc
                    )

            self._app_state.outputs_updated.emit()

            elapsed = loop.time() - start
            await asyncio.sleep(max(0.0, _EVAL_INTERVAL_S - elapsed))

    async def _handle_disconnect(self) -> None:
        for output in self._app_state.outputs:
            if not output.config.enabled or output.driver is None:
                continue
            match output.config.on_disconnect:
                case "force_off":
                    state = False
                case "force_on":
                    state = True
                case "hold":
                    continue
            try:
                await output.driver.set_state(state)
                output.last_output_state = state
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Output '%s' disconnect handler error: %s", output.config.name, exc
                )

    @staticmethod
    def _handle_pause_behavior(output: OutputInstance) -> bool | None:
        match output.config.on_pause:
            case "force_off": return False
            case "force_on":  return True
            case "hold":      return None

    @staticmethod
    def _handle_missing_input_behavior(output: OutputInstance) -> bool | None:
        match output.config.on_missing_input:
            case "force_off": return False
            case "force_on":  return True
            case "hold":      return None

    async def _handle_restim_autostart(self) -> None:
        cfg = self._app_state.config.player
        if not cfg.restim_autostart_enabled:
            return
        for base_url in cfg.restim_autostart_urls:
            base_url = base_url.rstrip("/")
            if not base_url:
                continue
            try:
                status_url = f"{base_url}/status"
                start_url = f"{base_url}/actions/start"

                def _get_status() -> dict:
                    with urllib.request.urlopen(status_url, timeout=3.0) as r:  # noqa: S310
                        return json.loads(r.read())

                def _do_start() -> None:
                    with urllib.request.urlopen(start_url, timeout=3.0) as r:  # noqa: S310
                        r.read()

                data = await asyncio.to_thread(_get_status)
                if not bool(data.get("playing", False)):
                    await asyncio.to_thread(_do_start)
                    logger.info("Restim autostart: started %s", base_url)
                else:
                    logger.debug("Restim autostart: %s already playing", base_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Restim autostart failed for %s: %s", base_url, exc)
