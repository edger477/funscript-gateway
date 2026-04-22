"""InputPoller — polls RestimInputs, manages AS5311 WebSocket connections,
and evaluates CalculatedInputs."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from typing import TYPE_CHECKING

import websockets

from funscript_gateway.models import (
    As5311Input,
    CalculatedInput,
    FunscriptAxisInput,
    RestimCondition,
    RestimInput,
)

if TYPE_CHECKING:
    from funscript_gateway.app_state import AppState

logger = logging.getLogger(__name__)

_LOOP_INTERVAL_S = 0.1  # inner loop tick — actual poll rate governed per-input


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=3.0) as resp:  # noqa: S310
        return json.loads(resp.read())


def _evaluate_restim_condition(cond: RestimCondition, data: dict) -> bool:
    playing = bool(data.get("playing", False))

    if cond.playing == "yes" and not playing:
        return False
    if cond.playing == "no" and playing:
        return False

    volume = data.get("volume", {}) or {}

    if cond.volume_ui_enabled:
        ui_vol = float(volume.get("ui", 0.0))
        if cond.volume_ui_above:
            if ui_vol <= cond.volume_ui_threshold:
                return False
        else:
            if ui_vol >= cond.volume_ui_threshold:
                return False

    if cond.volume_device_enabled:
        device_vol = volume.get("device")
        if device_vol is None:
            # device volume absent — condition cannot be met
            return False
        device_vol = float(device_vol)
        if cond.volume_device_above:
            if device_vol <= cond.volume_device_threshold:
                return False
        else:
            if device_vol >= cond.volume_device_threshold:
                return False

    return True


def _eval_calculated(inp: CalculatedInput, value_map: dict[str, float]) -> float:
    """Evaluate a CalculatedInput using left-to-right associativity.

    Result is 100.0 (true) or 0.0 (false).
    The first entry has no operator; each subsequent entry's operator is
    applied between the accumulated result and the entry's value.
    """
    if not inp.entries:
        return 0.0
    result = value_map.get(inp.entries[0].input_name, 0.0) >= 50.0
    for entry in inp.entries[1:]:
        val = value_map.get(entry.input_name, 0.0) >= 50.0
        match entry.operator:
            case "and":
                result = result and val
            case "or":
                result = result or val
            case "xor":
                result = result ^ val
    return 100.0 if result else 0.0


class InputPoller:
    """Polls RestimInputs, holds AS5311 WebSocket connections, evaluates CalculatedInputs.

    Runs as a long-lived async task on the same event loop as the rest of the app.
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_poll: dict[str, float] = {}  # input name → last poll time
        self._ws_tasks: dict[str, asyncio.Task] = {}  # input name → WS connection task

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.ensure_future(self._loop())

    async def stop(self) -> None:
        self._running = False
        for task in self._ws_tasks.values():
            task.cancel()
        if self._task is not None:
            self._task.cancel()
        tasks = list(self._ws_tasks.values())
        if self._task is not None:
            tasks.append(self._task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._ws_tasks.clear()
        self._task = None

    async def _loop(self) -> None:
        loop = asyncio.get_event_loop()
        while self._running:
            now = loop.time()
            for inp in list(self._app_state.inputs):
                if isinstance(inp, RestimInput) and inp.enabled:
                    last = self._last_poll.get(inp.name, -1e9)
                    if now - last >= inp.poll_interval_s:
                        await self._poll_restim(inp)
                        self._last_poll[inp.name] = now

            # One WS task per unique URL (shared across inputs with the same endpoint)
            active_urls = {
                inp.url
                for inp in self._app_state.inputs
                if isinstance(inp, As5311Input) and inp.enabled
            }
            for url in active_urls:
                task = self._ws_tasks.get(url)
                if task is None or task.done():
                    self._ws_tasks[url] = asyncio.ensure_future(
                        self._ws_loop_as5311(url)
                    )
            for url in list(self._ws_tasks):
                if url not in active_urls:
                    self._ws_tasks.pop(url).cancel()

            self._evaluate_calculated()
            await asyncio.sleep(_LOOP_INTERVAL_S)

    async def _poll_restim(self, inp: RestimInput) -> None:
        try:
            data = await asyncio.to_thread(_fetch_json, inp.url)
            met = _evaluate_restim_condition(inp.condition, data)
            inp.current_value = 100.0 if met else 0.0
            inp.is_error = False
            logger.debug("Restim '%s': condition=%s value=%.0f", inp.name, met, inp.current_value)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Restim poll '%s' failed: %s", inp.name, exc)
            inp.is_error = True
            inp.current_value = 100.0 if inp.default_value else 0.0

    def _as5311_inputs_for_url(self, url: str) -> list[As5311Input]:
        return [
            inp for inp in self._app_state.inputs
            if isinstance(inp, As5311Input) and inp.url == url
        ]

    async def _ws_loop_as5311(self, url: str) -> None:
        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    for inp in self._as5311_inputs_for_url(url):
                        inp.is_error = False
                    logger.debug("AS5311: connected to %s", url)
                    async for message in ws:
                        if not self._running:
                            return
                        data = json.loads(message)
                        x_m = float(data.get("x", 0.0))
                        x_mm = x_m * 1000.0
                        for inp in self._as5311_inputs_for_url(url):
                            inp.last_position_mm = x_mm
                            if inp.range_mm > 0:
                                inp.current_value = max(
                                    0.0,
                                    min(100.0, (x_mm - inp.threshold_mm) / inp.range_mm * 100.0),
                                )
                            else:
                                inp.current_value = 0.0
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                if not self._running:
                    return
                for inp in self._as5311_inputs_for_url(url):
                    inp.is_error = True
                logger.debug("AS5311 WS '%s' error: %s", url, exc)
                await asyncio.sleep(5.0)

    def _evaluate_calculated(self) -> None:
        # Build value lookup from all non-calculated inputs
        value_map: dict[str, float] = {
            inp.name: inp.current_value
            for inp in self._app_state.inputs
            if not isinstance(inp, CalculatedInput)
        }
        for inp in self._app_state.inputs:
            if isinstance(inp, CalculatedInput) and inp.enabled:
                inp.current_value = _eval_calculated(inp, value_map)

    def evaluate_calculated_now(self) -> None:
        """Evaluate calculated inputs immediately (called by OutputManager after axis update)."""
        self._evaluate_calculated()
