"""TasmotaDriver — controls a Tasmota smart relay via HTTP."""

from __future__ import annotations

import logging

import aiohttp

from funscript_gateway.models import TasmotaOutputConfig

logger = logging.getLogger(__name__)


class TasmotaDriver:
    """Sends on/off commands to a Tasmota device over HTTP.

    Commands are deduplicated: if the desired state matches the last
    successfully acknowledged state, no HTTP request is issued.
    """

    def __init__(
        self, config: TasmotaOutputConfig, session: aiohttp.ClientSession
    ) -> None:
        self.config = config
        self._session = session
        self._last_sent: bool | None = None

    async def set_state(self, on: bool) -> None:
        if on == self._last_sent:
            return
        cmd = "On" if on else "Off"
        url = (
            f"http://{self.config.host}/cm"
            f"?cmnd=Power{self.config.device_index}%20{cmd}"
        )
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_s)
        try:
            async with self._session.get(url, timeout=timeout) as resp:
                if resp.status == 200:
                    self._last_sent = on
                    logger.debug(
                        "Tasmota %s Power%d -> %s",
                        self.config.host,
                        self.config.device_index,
                        cmd,
                    )
                else:
                    logger.warning(
                        "Tasmota %s returned HTTP %d", self.config.host, resp.status
                    )
        except aiohttp.ClientError as exc:
            logger.warning("Tasmota %s HTTP error: %s", self.config.host, exc)
            raise
