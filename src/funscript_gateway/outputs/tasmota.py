"""TasmotaDriver — controls a Tasmota smart relay via HTTP."""

from __future__ import annotations

import asyncio
import logging
import urllib.error
import urllib.request

from funscript_gateway.models import TasmotaOutputConfig

logger = logging.getLogger(__name__)


class TasmotaDriver:
    """Sends on/off commands to a Tasmota device over HTTP.

    Commands are deduplicated: if the desired state matches the last
    successfully acknowledged state, no HTTP request is issued.

    Uses asyncio.to_thread + urllib to avoid event-loop socket compatibility
    issues on Windows (qasync / ProactorEventLoop).
    """

    def __init__(self, config: TasmotaOutputConfig) -> None:
        self.config = config
        self._last_sent: bool | None = None

    async def set_state(self, on: bool) -> None:
        if on == self._last_sent:
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
        logger.debug(
            "Tasmota %s Power%d -> %s",
            self.config.host,
            self.config.device_index,
            cmd,
        )
