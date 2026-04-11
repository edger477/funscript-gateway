"""HereSphere TCP player backend."""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from typing import Callable

from funscript_gateway.models import MediaConnectionState, PlayerState

logger = logging.getLogger(__name__)


class HereSphereBackend:
    """Async TCP client for the HereSphere player protocol.

    Wire format: 4-byte LE uint32 length header + UTF-8 JSON body.
    Keep-alive: a single 0x00 byte is sent by HereSphere every ~1000 ms
    when idle; it must be discarded without treating it as a length header.
    """

    def __init__(
        self,
        host: str,
        port: int,
        on_state_change: Callable[[PlayerState], None],
    ) -> None:
        self._host = host
        self._port = port
        self._on_state_change = on_state_change
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(
            self._host, self._port
        )
        logger.info("HereSphere connected to %s:%d", self._host, self._port)
        await self._read_loop(self._reader)

    async def disconnect(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._writer = None
        self._reader = None

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        """Read framed messages, discarding lone 0x00 keep-alive bytes."""
        while True:
            # Read the first byte of the header.
            first_byte = await reader.readexactly(1)
            if first_byte == b"\x00":
                # Keep-alive null byte — discard and wait for next message.
                continue
            # Read remaining 3 bytes to complete the 4-byte header.
            rest = await reader.readexactly(3)
            header = first_byte + rest
            if header == b"\x00\x00\x00\x00":
                # Null frame — discard.
                continue
            length: int = struct.unpack("<I", header)[0]
            if length == 0:
                continue
            data = await reader.readexactly(length)
            try:
                payload = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("HereSphere: failed to parse payload: %s", exc)
                continue
            self._handle_payload(payload)

    def _handle_payload(self, payload: dict) -> None:
        connection_state = self._derive_state(payload)
        current_time_ms = int(payload.get("currentTime", 0.0) * 1000)
        state = PlayerState(
            connection_state=connection_state,
            file_path=payload.get("path", "") or "",
            current_time_ms=current_time_ms,
            playback_speed=float(payload.get("playbackSpeed", 1.0)),
        )
        self._on_state_change(state)

    @staticmethod
    def _derive_state(payload: dict) -> MediaConnectionState:
        path = payload.get("path")
        if path in (None, ""):
            return MediaConnectionState.CONNECTED_BUT_NO_FILE_LOADED
        if payload.get("playerState") == 0:
            return MediaConnectionState.CONNECTED_AND_PLAYING
        return MediaConnectionState.CONNECTED_AND_PAUSED
