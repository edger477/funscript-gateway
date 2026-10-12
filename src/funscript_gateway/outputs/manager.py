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
from funscript_gateway.outputs.ws import WsDriver
from funscript_gateway.tasks import spawn

logger = logging.getLogger(__name__)

_EVAL_INTERVAL_S = 0.050  # 20 Hz
_RETRY_BACKOFF_MIN_S = 0.5
_RETRY_BACKOFF_MAX_S = 30.0
_SHUTDOWN_SEND_TIMEOUT_S = 3.0
_LOOP_ERROR_LOG_INTERVAL_S = 10.0


class OutputManager:
    """Manages the lifecycle of all output drivers and runs the evaluation loop.

    Driver sends never block the evaluation loop: each output delivers its
    latest desired state from its own background task, and a failing output
    backs off exponentially instead of being retried every tick.  A slow or
    unreachable device therefore cannot stall the other outputs.
    """

    def __init__(self, app_state: AppState, engine: FunscriptEngine) -> None:
        self._app_state = app_state
        self._engine = engine
        self._running = False
        self._task: asyncio.Task | None = None
        self._mqtt_drivers: list[MqttDriver] = []
        self._ws_drivers: list[WsDriver] = []
        self._was_connected: bool = False
        self._was_playing: bool = False
        self._reload_lock = asyncio.Lock()
        self._autostart_task: asyncio.Task | None = None
        self._last_loop_error_log: float = float("-inf")

    async def start(self) -> None:
        self._running = True
        async with self._reload_lock:
            await self._setup_outputs()
        self._task = asyncio.ensure_future(self._evaluation_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._autostart_task is not None:
            self._autostart_task.cancel()
        async with self._reload_lock:
            self._cancel_sends()
            await self._send_disconnect_states()
            await self._disconnect_mqtt_drivers()
            await self._disconnect_ws_drivers()

    async def reload_outputs(self) -> None:
        """Rebuild all output instances from the current config (called after UI changes)."""
        async with self._reload_lock:
            self._cancel_sends()
            await self._disconnect_mqtt_drivers()
            await self._disconnect_ws_drivers()
            await self._setup_outputs()
        self._app_state.outputs_updated.emit()

    def _cancel_sends(self) -> None:
        for output in self._app_state.outputs:
            task = output.send_task
            if task is not None and not task.done():
                task.cancel()
            output.send_task = None

    async def _disconnect_mqtt_drivers(self) -> None:
        drivers, self._mqtt_drivers = self._mqtt_drivers, []
        for driver in drivers:
            try:
                await driver.disconnect()
            except Exception:  # noqa: BLE001
                pass

    async def _disconnect_ws_drivers(self) -> None:
        drivers, self._ws_drivers = self._ws_drivers, []
        for driver in drivers:
            try:
                await driver.disconnect()
            except Exception:  # noqa: BLE001
                pass

    async def _setup_outputs(self) -> None:
        """Instantiate one OutputInstance per entry in app_state.config.outputs.

        The list is index-aligned with config.outputs; an output whose driver
        could not be created gets ``driver=None`` and is skipped at runtime.
        """
        outputs: list[OutputInstance] = []
        for cfg in self._app_state.config.outputs:
            outputs.append(await self._create_output_instance(cfg))
        self._app_state.outputs = outputs

    async def _create_output_instance(self, cfg: OutputConfig) -> OutputInstance:
        processor = ThresholdSwitchProcessor(cfg.threshold) if cfg.type != "ws_value" else None
        driver = await self._create_driver(cfg)
        return OutputInstance(config=cfg, processor=processor, driver=driver)

    async def _create_driver(self, cfg: OutputConfig) -> object | None:
        match cfg.type:
            case "threshold_tasmota":
                return TasmotaDriver(cfg.tasmota)
            case "threshold_mqtt":
                driver = MqttDriver(cfg.mqtt)
                try:
                    await driver.connect()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Output '%s': MQTT connection failed (%s); "
                        "output will be inactive until reload.",
                        cfg.name, exc,
                    )
                    try:
                        await driver.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
                    return None
                self._mqtt_drivers.append(driver)
                return driver
            case "ws_value":
                driver = WsDriver(cfg.ws)
                await driver.connect()
                self._ws_drivers.append(driver)
                return driver
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
            try:
                self._evaluate_once()
            except Exception:  # noqa: BLE001
                # Never let one bad tick kill the loop; rate-limit the log.
                if start - self._last_loop_error_log >= _LOOP_ERROR_LOG_INTERVAL_S:
                    self._last_loop_error_log = start
                    logger.exception("Output evaluation error")
            elapsed = loop.time() - start
            await asyncio.sleep(max(0.0, _EVAL_INTERVAL_S - elapsed))

    def _evaluate_once(self) -> None:
        player_state = self._app_state.player_state
        connection_state = player_state.connection_state
        is_connected = connection_state != MediaConnectionState.NOT_CONNECTED
        is_playing = connection_state == MediaConnectionState.CONNECTED_AND_PLAYING

        # Detect disconnect transition.
        if not is_connected and self._was_connected:
            self._handle_disconnect()
            self._was_connected = False
        elif is_connected:
            self._was_connected = True

        # Detect play-start transition → restim autostart (in the background).
        if is_playing and not self._was_playing:
            if self._autostart_task is None or self._autostart_task.done():
                self._autostart_task = spawn(
                    self._handle_restim_autostart(), "restim autostart"
                )
        self._was_playing = is_playing

        if is_playing:
            self._engine.update_values(self._app_state.current_time_ms)

        for output in self._app_state.outputs:
            if not output.config.enabled:
                continue
            if output.driver is None:
                continue

            # WebSocket continuous-value outputs: pass raw input value, no threshold
            if output.config.type == "ws_value":
                inp = self._resolve_input(output.config.input_name)
                if inp is not None and self._input_is_available(inp):
                    if isinstance(inp, FunscriptAxisInput):
                        raw_value = inp.current_value if is_playing else 0.0
                    elif not is_playing:
                        raw_value = 0.0
                    else:
                        raw_value = inp.current_value
                else:
                    raw_value = 0.0
                output.last_input_value = raw_value
                output.driver.set_value(raw_value)
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
                # All non-funscript inputs respect on_pause when player is not playing.
                if not is_playing:
                    forced = self._handle_pause_behavior(output)
                    if forced is None:
                        continue
                    new_state = forced
                else:
                    new_state = output.processor.process(inp.current_value)
                    output.last_input_value = inp.current_value

            output.last_output_state = new_state
            self._dispatch(output, new_state)

    def _dispatch(self, output: OutputInstance, state: bool) -> None:
        """Hand ``state`` to the output's sender task without waiting for it."""
        output.pending_state = state
        if output.send_task is not None and not output.send_task.done():
            return  # the in-flight sender picks up the latest pending_state
        if asyncio.get_event_loop().time() < output.retry_at:
            return  # backing off after a failure
        output.send_task = asyncio.ensure_future(self._send(output))

    async def _send(self, output: OutputInstance) -> None:
        loop = asyncio.get_event_loop()
        while True:
            state = output.pending_state
            try:
                await output.driver.set_state(state)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                output.consecutive_errors += 1
                if output.consecutive_errors >= 3:
                    output.is_degraded = True
                backoff = min(
                    _RETRY_BACKOFF_MAX_S,
                    _RETRY_BACKOFF_MIN_S * 2 ** (output.consecutive_errors - 1),
                )
                output.retry_at = loop.time() + backoff
                logger.warning(
                    "Output '%s' driver error: %s (retry in %.1fs)",
                    output.config.name, exc, backoff,
                )
                return
            output.consecutive_errors = 0
            output.is_degraded = False
            output.retry_at = 0.0
            if output.pending_state == state:
                return

    @staticmethod
    def _disconnect_state(output: OutputInstance) -> bool | None:
        match output.config.on_disconnect:
            case "force_off": return False
            case "force_on":  return True
            case _:           return None  # "hold"

    def _handle_disconnect(self) -> None:
        for output in self._app_state.outputs:
            if not output.config.enabled or output.driver is None:
                continue
            state = self._disconnect_state(output)
            if state is None:
                continue
            output.last_output_state = state
            output.retry_at = 0.0  # deliver the disconnect state promptly
            self._dispatch(output, state)

    async def _send_disconnect_states(self) -> None:
        """On shutdown, deliver each output's on_disconnect state (bounded wait)."""
        sends = []
        names = []
        for output in self._app_state.outputs:
            if not output.config.enabled or output.driver is None:
                continue
            state = self._disconnect_state(output)
            if state is None:
                continue
            if output.consecutive_errors > 0:
                # Known unreachable — a blocking attempt would only delay exit
                # (the worker thread cannot be cancelled and is joined at exit).
                logger.info(
                    "Output '%s': skipping disconnect state, device unreachable.",
                    output.config.name,
                )
                continue
            sends.append(
                asyncio.wait_for(output.driver.set_state(state), _SHUTDOWN_SEND_TIMEOUT_S)
            )
            names.append(output.config.name)
        results = await asyncio.gather(*sends, return_exceptions=True)
        for name, result in zip(names, results):
            if isinstance(result, BaseException):
                logger.warning("Output '%s' disconnect handler error: %r", name, result)

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
        urls = [u.rstrip("/") for u in cfg.restim_autostart_urls if u.rstrip("/")]
        await asyncio.gather(*(self._autostart_one(u) for u in urls))

    @staticmethod
    async def _autostart_one(base_url: str) -> None:
        status_url = f"{base_url}/status"
        start_url = f"{base_url}/actions/start"

        def _get_status() -> dict:
            with urllib.request.urlopen(status_url, timeout=3.0) as r:  # noqa: S310
                return json.loads(r.read())

        def _do_start() -> None:
            with urllib.request.urlopen(start_url, timeout=3.0) as r:  # noqa: S310
                r.read()

        try:
            data = await asyncio.to_thread(_get_status)
            if not bool(data.get("playing", False)):
                await asyncio.to_thread(_do_start)
                logger.info("Restim autostart: started %s", base_url)
            else:
                logger.debug("Restim autostart: %s already playing", base_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Restim autostart failed for %s: %s", base_url, exc)
