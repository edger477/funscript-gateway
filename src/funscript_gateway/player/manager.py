"""PlayerConnectionManager — maintains persistent connection to the active player backend."""

from __future__ import annotations

import asyncio
import logging
import time

from funscript_gateway.app_state import AppState
from funscript_gateway.models import MediaConnectionState, PlayerState

logger = logging.getLogger(__name__)

_RETRY_DELAY_S = 5.0
_STALE_TIMESTAMP_S = 5.0
_WATCHDOG_INTERVAL_S = 1.0


class PlayerConnectionManager:
    """Manages connection to the configured player backend.

    Retries on any error after a 5-second delay. Emits
    ``app_state.player_state_changed`` whenever the player state updates.
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._running = False
        self._last_time_ms: int | None = None
        self._last_time_changed_at: float = 0.0

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.ensure_future(self._run())
        self._watchdog_task = asyncio.ensure_future(self._watchdog_loop())

    async def stop(self) -> None:
        self._running = False
        for task in (self._task, self._watchdog_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._task = None
        self._watchdog_task = None

    def _apply_stale_timestamp_detection(self, state: PlayerState) -> PlayerState:
        """Override PLAYING→PAUSED when the timestamp has been frozen for too long."""
        if state.connection_state != MediaConnectionState.CONNECTED_AND_PLAYING:
            self._last_time_ms = None
            self._last_time_changed_at = 0.0
            return state

        now = time.monotonic()
        if state.current_time_ms != self._last_time_ms:
            self._last_time_ms = state.current_time_ms
            self._last_time_changed_at = now
        elif now - self._last_time_changed_at >= _STALE_TIMESTAMP_S:
            logger.debug(
                "Timestamp frozen for %.1fs — treating as paused",
                now - self._last_time_changed_at,
            )
            return PlayerState(
                connection_state=MediaConnectionState.CONNECTED_AND_PAUSED,
                file_path=state.file_path,
                current_time_ms=state.current_time_ms,
                playback_speed=state.playback_speed,
            )
        return state

    def _on_state_change(self, state: PlayerState) -> None:
        state = self._apply_stale_timestamp_detection(state)
        self._app_state.player_state = state
        self._app_state.current_time_ms = state.current_time_ms
        self._app_state.player_state_changed.emit(state)

    def _reevaluate(self) -> None:
        """Re-apply stale-timestamp detection to the current state, on a timer.

        Backends only call ``_on_state_change`` when the player pushes an
        update. A player that goes silent — or, for HereSphere, keeps the
        connection alive but sends only keep-alive bytes — would otherwise
        never be re-checked, leaving outputs running against a frozen
        timestamp. This lets the frozen->paused rule fire without new payloads.
        """
        current = self._app_state.player_state
        if current.connection_state != MediaConnectionState.CONNECTED_AND_PLAYING:
            return
        updated = self._apply_stale_timestamp_detection(current)
        if updated.connection_state != current.connection_state:
            self._app_state.player_state = updated
            self._app_state.current_time_ms = updated.current_time_ms
            self._app_state.player_state_changed.emit(updated)

    async def _watchdog_loop(self) -> None:
        while self._running:
            await asyncio.sleep(_WATCHDOG_INTERVAL_S)
            try:
                self._reevaluate()
            except Exception:  # noqa: BLE001
                logger.exception("Player watchdog error")

    async def _run(self) -> None:
        while self._running:
            backend = self._create_backend()
            try:
                await backend.connect()
            except asyncio.CancelledError:
                await backend.disconnect()
                raise
            except Exception as exc:
                logger.info(
                    "Player backend error (%s); retrying in %.0fs.",
                    exc,
                    _RETRY_DELAY_S,
                )
            finally:
                await backend.disconnect()

            # Reset stale-timestamp tracking so the next connection starts fresh.
            self._last_time_ms = None
            self._last_time_changed_at = 0.0

            # Emit NOT_CONNECTED state so UI reflects the disconnection.
            disconnected = PlayerState(
                connection_state=MediaConnectionState.NOT_CONNECTED
            )
            self._on_state_change(disconnected)

            if not self._running:
                break
            await asyncio.sleep(_RETRY_DELAY_S)

    def _create_backend(self):
        cfg = self._app_state.config.player
        match cfg.type:
            case "mpc_hc":
                from funscript_gateway.player.mpc_hc import MpcHcBackend
                return MpcHcBackend(
                    host=cfg.host,
                    port=cfg.port,
                    poll_interval_ms=cfg.poll_interval_ms,
                    on_state_change=self._on_state_change,
                )
            case _:
                from funscript_gateway.player.heresphere import HereSphereBackend
                return HereSphereBackend(
                    host=cfg.host,
                    port=cfg.port,
                    on_state_change=self._on_state_change,
                )
