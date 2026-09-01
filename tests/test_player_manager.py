"""Tests for PlayerConnectionManager stale/silent-player handling."""

import asyncio

import pytest

from funscript_gateway.app_state import AppState
from funscript_gateway.models import MediaConnectionState, PlayerState
from funscript_gateway.player import manager as manager_module
from funscript_gateway.player.manager import PlayerConnectionManager


def _playing(ts_ms: int) -> PlayerState:
    return PlayerState(
        connection_state=MediaConnectionState.CONNECTED_AND_PLAYING,
        file_path="/v.mp4",
        current_time_ms=ts_ms,
        playback_speed=1.0,
    )


class TestStaleReevaluation:
    def test_reevaluate_flips_playing_to_paused_without_new_payload(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(manager_module.time, "monotonic", lambda: clock[0])

        app_state = AppState()
        mgr = PlayerConnectionManager(app_state)

        mgr._on_state_change(_playing(5000))
        assert app_state.player_state.connection_state == MediaConnectionState.CONNECTED_AND_PLAYING

        # No further payloads; wall clock advances past the stale threshold.
        clock[0] += manager_module._STALE_TIMESTAMP_S + 0.1
        mgr._reevaluate()

        assert app_state.player_state.connection_state == MediaConnectionState.CONNECTED_AND_PAUSED

    def test_reevaluate_noop_while_timestamp_advances(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(manager_module.time, "monotonic", lambda: clock[0])

        app_state = AppState()
        mgr = PlayerConnectionManager(app_state)
        mgr._on_state_change(_playing(5000))

        for i in range(1, 10):
            clock[0] += 1.0
            mgr._on_state_change(_playing(5000 + i * 1000))
            mgr._reevaluate()
            assert app_state.player_state.connection_state == MediaConnectionState.CONNECTED_AND_PLAYING

    def test_reevaluate_ignores_non_playing_state(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(manager_module.time, "monotonic", lambda: clock[0])

        app_state = AppState()
        mgr = PlayerConnectionManager(app_state)
        mgr._on_state_change(
            PlayerState(connection_state=MediaConnectionState.CONNECTED_AND_PAUSED, file_path="/v.mp4")
        )
        clock[0] += 100.0
        mgr._reevaluate()
        assert app_state.player_state.connection_state == MediaConnectionState.CONNECTED_AND_PAUSED

    @pytest.mark.asyncio
    async def test_watchdog_loop_marks_frozen_player_paused(self, monkeypatch):
        # Note: don't monkeypatch time.monotonic here — the event loop's timers
        # depend on it. Simulate elapsed time by ageing _last_time_changed_at.
        monkeypatch.setattr(manager_module, "_WATCHDOG_INTERVAL_S", 0.01)

        app_state = AppState()
        mgr = PlayerConnectionManager(app_state)
        mgr._running = True
        mgr._on_state_change(_playing(5000))
        mgr._last_time_changed_at -= manager_module._STALE_TIMESTAMP_S + 1.0

        task = asyncio.ensure_future(mgr._watchdog_loop())
        try:
            await asyncio.sleep(0.05)
        finally:
            mgr._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert app_state.player_state.connection_state == MediaConnectionState.CONNECTED_AND_PAUSED
