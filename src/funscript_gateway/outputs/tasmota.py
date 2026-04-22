"""TasmotaDriver — controls a Tasmota smart relay via HTTP."""

from __future__ import annotations

import asyncio
import logging
import time
import urllib.error
import urllib.request

from funscript_gateway.models import TasmotaOutputConfig

logger = logging.getLogger(__name__)


class TasmotaDriver:
    """Sends on/off commands to a Tasmota device over HTTP.

    When repeat_interval_s > 0, the ON command is re-sent periodically so that
    a Tasmota device configured in pulse mode (e.g. PulseTime1 160) keeps its
    relay closed even if a prior network request was lost.

    Uses asyncio.to_thread + urllib to avoid event-loop socket compatibility
    issues on Windows (qasync / ProactorEventLoop).
    """

    def __init__(self, config: TasmotaOutputConfig) -> None:
        self.config = config
        self._last_sent: bool | None = None
        self._last_send_time: float = 0.0

    async def set_state(self, on: bool) -> None:
        repeat = self.config.repeat_interval_s
        now = time.monotonic()

        if on == self._last_sent:
            # Re-send ON if repeat interval has elapsed; always skip OFF repeats.
            if not on or repeat <= 0 or (now - self._last_send_time) < repeat:
                return

        cmd = "On" if on else "Off"
        url = (
            f"http://{self.config.host}/cm"
            f"?cmnd=Power{self.config.device_index}%20{cmd}"
        )
        timeout = self.config.timeout_s

        def do_request() -> None:
            req = urllib.request.urlopen(url, timeout=timeout)
            req.read()
            req.close()

        await asyncio.to_thread(do_request)
        self._last_sent = on
        self._last_send_time = now
        logger.debug(
            "Tasmota %s Power%d -> %s",
            self.config.host,
            self.config.device_index,
            cmd,
        )
