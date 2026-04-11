"""OutputManager — 20 Hz evaluation loop that drives all configured outputs."""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from funscript_gateway.app_state import AppState
from funscript_gateway.funscript.engine import FunscriptEngine, interpolate
from funscript_gateway.models import (
    FunscriptAxis,
    MediaConnectionState,
    OutputConfig,
    OutputInstance,
)
from funscript_gateway.outputs.tasmota import TasmotaDriver
from funscript_gateway.outputs.threshold import ThresholdSwitchProcessor

logger = logging.getLogger(__name__)

try:
    import aiomqtt
    _AIOMQTT_AVAILABLE = True
except ImportError:
    _AIOMQTT_AVAILABLE = False

_EVAL_INTERVAL_S = 0.050  # 20 Hz


class OutputManager:
    """Manages the lifecycle of all output drivers and runs the evaluation loop."""

    def __init__(self, app_state: AppState, engine: FunscriptEngine) -> None:
        self._app_state = app_state
        self._engine = engine
        self._running = False
        self._task: asyncio.Task | None = None
        self._http_session: aiohttp.ClientSession | None = None
        # key: (broker_host, broker_port) -> aiomqtt.Client context
        self._mqtt_clients: dict[tuple[str, int], object] = {}
        self._mqtt_status_tasks: list[asyncio.Task] = []
        self._was_connected: bool = False

    async def start(self) -> None:
        self._running = True
        self._http_session = aiohttp.ClientSession()
        await self._setup_outputs()
        self._task = asyncio.ensure_future(self._evaluation_loop())

    async def stop(self) -> None:
        self._running = False
        # Apply on_disconnect behavior before shutting down.
        await self._handle_disconnect()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        # Cancel status subscription tasks.
        for t in self._mqtt_status_tasks:
            t.cancel()
        self._mqtt_status_tasks.clear()
        # Exit MQTT client contexts.
        for client in self._mqtt_clients.values():
            try:
                await client.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        self._mqtt_clients.clear()
        if self._http_session is not None:
            await self._http_session.close()
            self._http_session = None

    async def reload_outputs(self) -> None:
        """Rebuild all output instances from the current config (called after UI changes)."""
        # Clean up existing MQTT subscriptions and connections before rebuilding.
        for t in self._mqtt_status_tasks:
            t.cancel()
        self._mqtt_status_tasks.clear()
        for client in self._mqtt_clients.values():
            try:
                await client.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        self._mqtt_clients.clear()
        await self._setup_outputs()
        self._app_state.outputs_updated.emit()

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
                return TasmotaDriver(cfg.tasmota, self._http_session)
            case "threshold_mqtt":
                if not _AIOMQTT_AVAILABLE:
                    logger.warning(
                        "Output '%s' skipped: aiomqtt not available.", cfg.name
                    )
                    return None
                key = (cfg.mqtt.broker_host, cfg.mqtt.broker_port)
                if key not in self._mqtt_clients:
                    client = aiomqtt.Client(
                        cfg.mqtt.broker_host, port=cfg.mqtt.broker_port
                    )
                    await client.__aenter__()
                    self._mqtt_clients[key] = client
                client = self._mqtt_clients[key]
                from funscript_gateway.outputs.mqtt import MqttDriver
                driver = MqttDriver(cfg.mqtt, client)
                if cfg.mqtt.status_topic:
                    task = asyncio.ensure_future(driver.run_status_subscription())
                    self._mqtt_status_tasks.append(task)
                return driver
            case _:
                logger.warning("Unknown output type '%s' for '%s'.", cfg.type, cfg.name)
                return None

    def _resolve_axis(self, axis_name: str) -> FunscriptAxis | None:
        for axis in self._app_state.axes:
            if axis.name == axis_name:
                return axis
        return None

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

            if is_playing:
                self._engine.update_values(self._app_state.current_time_ms)

            for output in self._app_state.outputs:
                if not output.config.enabled:
                    continue

                if output.driver is None:
                    continue

                axis = self._resolve_axis(output.config.axis_name)
                axis_available = axis is not None and axis.enabled and not axis.file_missing

                if not axis_available:
                    forced = self._handle_missing_axis_behavior(output)
                    if forced is None:
                        continue
                    new_state = forced
                elif is_playing:
                    new_state = output.processor.process(axis.current_value)
                    output.last_input_value = axis.current_value
                else:
                    forced = self._handle_pause_behavior(output)
                    if forced is None:
                        continue
                    new_state = forced

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
    def _handle_missing_axis_behavior(output: OutputInstance) -> bool | None:
        match output.config.on_missing_axis:
            case "force_off": return False
            case "force_on":  return True
            case "hold":      return None
