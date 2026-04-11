"""Tests for HereSphere protocol parsing logic (pure function tests, no network)."""

import asyncio
import struct

import pytest

from funscript_gateway.models import MediaConnectionState
from funscript_gateway.player.heresphere import HereSphereBackend


def make_backend() -> HereSphereBackend:
    states = []
    return HereSphereBackend(
        host="127.0.0.1",
        port=23554,
        on_state_change=states.append,
    ), states


class TestDeriveState:
    def test_no_path_returns_no_file(self):
        state = HereSphereBackend._derive_state({"playerState": 0, "path": None})
        assert state == MediaConnectionState.CONNECTED_BUT_NO_FILE_LOADED

    def test_empty_path_returns_no_file(self):
        state = HereSphereBackend._derive_state({"playerState": 0, "path": ""})
        assert state == MediaConnectionState.CONNECTED_BUT_NO_FILE_LOADED

    def test_missing_path_key_returns_no_file(self):
        state = HereSphereBackend._derive_state({"playerState": 0})
        assert state == MediaConnectionState.CONNECTED_BUT_NO_FILE_LOADED

    def test_player_state_0_is_playing(self):
        state = HereSphereBackend._derive_state(
            {"playerState": 0, "path": "C:/Videos/test.mp4"}
        )
        assert state == MediaConnectionState.CONNECTED_AND_PLAYING

    def test_player_state_nonzero_is_paused(self):
        for val in (1, 2, 3, -1, 10):
            state = HereSphereBackend._derive_state(
                {"playerState": val, "path": "C:/Videos/test.mp4"}
            )
            assert state == MediaConnectionState.CONNECTED_AND_PAUSED, f"Failed for playerState={val}"

    def test_missing_player_state_key_is_paused(self):
        # Missing key means get() returns None, which is not 0 → paused
        state = HereSphereBackend._derive_state({"path": "C:/Videos/test.mp4"})
        assert state == MediaConnectionState.CONNECTED_AND_PAUSED


class TestHandlePayload:
    def test_handle_payload_playing(self):
        backend, states = make_backend()
        payload = {
            "playerState": 0,
            "currentTime": 42.317,
            "path": "C:/Videos/example.mp4",
            "playbackSpeed": 1.0,
        }
        backend._handle_payload(payload)
        assert len(states) == 1
        s = states[0]
        assert s.connection_state == MediaConnectionState.CONNECTED_AND_PLAYING
        assert s.file_path == "C:/Videos/example.mp4"
        assert s.current_time_ms == 42317
        assert s.playback_speed == 1.0

    def test_handle_payload_paused(self):
        backend, states = make_backend()
        payload = {
            "playerState": 1,
            "currentTime": 10.0,
            "path": "C:/Videos/example.mp4",
            "playbackSpeed": 1.0,
        }
        backend._handle_payload(payload)
        assert states[0].connection_state == MediaConnectionState.CONNECTED_AND_PAUSED

    def test_handle_payload_no_file(self):
        backend, states = make_backend()
        payload = {"playerState": 0, "currentTime": 0.0, "path": "", "playbackSpeed": 1.0}
        backend._handle_payload(payload)
        assert states[0].connection_state == MediaConnectionState.CONNECTED_BUT_NO_FILE_LOADED

    def test_handle_payload_time_conversion(self):
        backend, states = make_backend()
        # 1.5 seconds → 1500 ms
        payload = {
            "playerState": 0,
            "currentTime": 1.5,
            "path": "/video.mp4",
            "playbackSpeed": 2.0,
        }
        backend._handle_payload(payload)
        assert states[0].current_time_ms == 1500
        assert states[0].playback_speed == 2.0

    def test_handle_payload_missing_current_time_defaults_to_zero(self):
        backend, states = make_backend()
        payload = {"playerState": 0, "path": "/video.mp4"}
        backend._handle_payload(payload)
        assert states[0].current_time_ms == 0

    def test_handle_payload_none_path_treated_as_empty(self):
        backend, states = make_backend()
        payload = {"playerState": 0, "path": None, "currentTime": 0.0}
        backend._handle_payload(payload)
        assert states[0].file_path == ""


class TestReadLoopFraming:
    """Test the framing logic via a mock StreamReader."""

    def _make_message(self, json_bytes: bytes) -> bytes:
        header = struct.pack("<I", len(json_bytes))
        return header + json_bytes

    @pytest.mark.asyncio
    async def test_read_loop_discards_null_byte(self):
        """A single 0x00 keep-alive byte is discarded; the next frame is parsed."""
        import json as _json

        backend, states = make_backend()
        payload = _json.dumps(
            {"playerState": 0, "currentTime": 1.0, "path": "/v.mp4", "playbackSpeed": 1.0}
        ).encode()
        frame = self._make_message(payload)
        # Prepend a null keep-alive byte
        data = b"\x00" + frame

        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()

        try:
            await asyncio.wait_for(backend._read_loop(reader), timeout=1.0)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass

        assert len(states) >= 1
        assert states[0].connection_state == MediaConnectionState.CONNECTED_AND_PLAYING

    @pytest.mark.asyncio
    async def test_read_loop_parses_valid_frame(self):
        import json as _json

        backend, states = make_backend()
        payload = _json.dumps(
            {"playerState": 1, "currentTime": 5.0, "path": "/test.mp4", "playbackSpeed": 0.5}
        ).encode()
        frame = self._make_message(payload)

        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()

        try:
            await asyncio.wait_for(backend._read_loop(reader), timeout=1.0)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass

        assert len(states) >= 1
        assert states[0].current_time_ms == 5000
        assert states[0].playback_speed == 0.5

    @pytest.mark.asyncio
    async def test_read_loop_multiple_frames(self):
        import json as _json

        backend, states = make_backend()
        payloads = [
            {"playerState": 0, "currentTime": 1.0, "path": "/a.mp4", "playbackSpeed": 1.0},
            {"playerState": 0, "currentTime": 2.0, "path": "/a.mp4", "playbackSpeed": 1.0},
        ]
        data = b"".join(
            self._make_message(_json.dumps(p).encode()) for p in payloads
        )

        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()

        try:
            await asyncio.wait_for(backend._read_loop(reader), timeout=1.0)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass

        assert len(states) >= 2
        assert states[0].current_time_ms == 1000
        assert states[1].current_time_ms == 2000
