"""MPC-HC HTTP polling player backend."""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.error
import urllib.request
from typing import Callable

from funscript_gateway.models import MediaConnectionState, PlayerState

logger = logging.getLogger(__name__)

RE_STATE = re.compile(r'id="state"[^>]*>(-?\d+)<')
RE_FILEPATH = re.compile(r'id="filepath"[^>]*>([^<]*)<')
RE_POSITION = re.compile(r'id="position"[^>]*>(\d+)<')
RE_PLAYBACKRATE = re.compile(r'id="playbackrate"[^>]*>([0-9.]+)<')


class MpcHcBackend:
    """HTTP polling backend for MPC-HC.

    Polls /variables.html at a configurable interval and extracts state
    via regex. Position is returned in milliseconds by MPC-HC.

    Uses asyncio.to_thread + urllib to avoid event-loop socket compatibility
    issues on Windows (qasync / ProactorEventLoop).
    """

    def __init__(
        self,
        host: str,
        port: int,
        poll_interval_ms: int,
        on_state_change: Callable[[PlayerState], None],
    ) -> None:
        self._host = host
        self._port = port
        self._poll_interval_s = poll_interval_ms / 1000.0
        self._on_state_change = on_state_change
        self._url = f"http://{host}:{port}/variables.html"

    async def connect(self) -> None:
        """Poll MPC-HC indefinitely until cancelled."""
        logger.info("MPC-HC polling %s", self._url)
        while True:
            try:
                body = await asyncio.to_thread(self._fetch)
                state = self._parse_response(body)
                self._on_state_change(state)
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                logger.debug("MPC-HC poll error: %s", exc)
                raise
            await asyncio.sleep(self._poll_interval_s)

    def _fetch(self) -> str:
        with urllib.request.urlopen(self._url, timeout=2.0) as resp:
            return resp.read().decode("utf-8", errors="replace")

    async def disconnect(self) -> None:
        pass

    def _parse_response(self, body: str) -> PlayerState:
        state_match = RE_STATE.search(body)
        filepath_match = RE_FILEPATH.search(body)
        position_match = RE_POSITION.search(body)
        rate_match = RE_PLAYBACKRATE.search(body)

        state_val = int(state_match.group(1)) if state_match else -1
        filepath = filepath_match.group(1).strip() if filepath_match else ""
        position_ms = int(position_match.group(1)) if position_match else 0
        playback_rate = float(rate_match.group(1)) if rate_match else 1.0

        connection_state = self._derive_state(state_val, filepath)
        return PlayerState(
            connection_state=connection_state,
            file_path=filepath,
            current_time_ms=position_ms,
            playback_speed=playback_rate,
        )

    @staticmethod
    def _derive_state(state_val: int, filepath: str) -> MediaConnectionState:
        if state_val == -1 or not filepath:
            return MediaConnectionState.CONNECTED_BUT_NO_FILE_LOADED
        if state_val == 2:
            return MediaConnectionState.CONNECTED_AND_PLAYING
        return MediaConnectionState.CONNECTED_AND_PAUSED
