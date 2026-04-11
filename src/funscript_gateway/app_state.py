"""Shared mutable application state and Qt signals hub."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from funscript_gateway.models import (
    FunscriptAxis,
    GatewayConfig,
    OutputInstance,
    PlayerState,
)


class AppState(QObject):
    """Central state object shared by all application components.

    Signals are emitted from async tasks and consumed by Qt UI widgets.
    Because qasync runs the asyncio loop on the Qt main thread, signal
    emission is safe without cross-thread marshalling.
    """

    player_state_changed = Signal(object)  # carries PlayerState
    axes_updated = Signal(list)            # carries list[FunscriptAxis]
    outputs_updated = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.config: GatewayConfig = GatewayConfig()
        self.player_state: PlayerState = PlayerState()
        self.current_time_ms: int = 0
        self.axes: list[FunscriptAxis] = []
        self.outputs: list[OutputInstance] = []
