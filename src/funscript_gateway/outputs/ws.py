"""WsDriver — sends continuous value updates to a WebSocket endpoint.

Maintains a persistent connection and sends {"field": value} JSON at a
configurable interval. The input value (0–100) is linearly mapped to the
configured min/max output range before sending.

Uses websockets (already a project dependency) which is compatible with the
Windows ProactorEventLoop used by qasync.
"""

from __future__ import annotations

import asyncio
import json
import logging

import websockets

from funscript_gateway.models import WsOutputConfig

logger = logging.getLogger(__name__)


class WsDriver:
    """Sends a continuously-updated value to a WebSocket endpoint.

    Lifecycle:
      await driver.connect()      — starts the background WS loop
      driver.set_value(float)     — update the input value (0–100); non-blocking
      await driver.disconnect()   — stops the loop and closes the connection
    """

    def __init__(self, config: WsOutputConfig) -> None:
        self.config = config
        self._input_value: float = 0.0   # raw 0–100 from the input
        self._running = False
        self._task: asyncio.Task | None = None

    def _mapped_value(self) -> float:
        """Map current input (0–100) to configured output range."""
        span = self.config.max_output - self.config.min_output
        return self.config.min_output + span * self._input_value / 100.0

    def set_value(self, input_value: float) -> None:
        """Update the raw input value (0–100). Thread-safe from the eval loop."""
        self._input_value = max(0.0, min(100.0, input_value))

    async def connect(self) -> None:
        self._running = True
        self._task = asyncio.ensure_future(self._ws_loop())

    async def disconnect(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _ws_loop(self) -> None:
        while self._running:
            try:
                async with websockets.connect(self.config.url) as ws:
                    logger.debug("WsDriver: connected to %s", self.config.url)
                    while self._running:
                        payload = json.dumps({self.config.field_name: self._mapped_value()})
                        await ws.send(payload)
                        await asyncio.sleep(self.config.send_interval_s)
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                if not self._running:
                    return
                logger.debug("WsDriver '%s' error: %s", self.config.url, exc)
                await asyncio.sleep(5.0)
