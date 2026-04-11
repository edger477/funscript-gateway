"""PlayerConnectionManager — maintains persistent connection to the active player backend."""

from __future__ import annotations

import asyncio
import logging

from funscript_gateway.app_state import AppState
from funscript_gateway.models import MediaConnectionState, PlayerState

logger = logging.getLogger(__name__)

_RETRY_DELAY_S = 5.0


class PlayerConnectionManager:
    """Manages connection to the configured player backend.

    Retries on any error after a 5-second delay. Emits
    ``app_state.player_state_changed`` whenever the player state updates.
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    def _on_state_change(self, state: PlayerState) -> None:
        self._app_state.player_state = state
        self._app_state.current_time_ms = state.current_time_ms
        self._app_state.player_state_changed.emit(state)

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
