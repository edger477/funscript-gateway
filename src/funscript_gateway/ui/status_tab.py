"""Status tab — live player connection information."""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QWidget

from funscript_gateway.models import MediaConnectionState, PlayerState

_STATE_LABELS = {
    MediaConnectionState.NOT_CONNECTED: ("NOT CONNECTED", "#e74c3c"),
    MediaConnectionState.CONNECTED_BUT_NO_FILE_LOADED: ("CONNECTED — NO FILE", "#f39c12"),
    MediaConnectionState.CONNECTED_AND_PAUSED: ("CONNECTED — PAUSED", "#f39c12"),
    MediaConnectionState.CONNECTED_AND_PLAYING: ("CONNECTED — PLAYING", "#27ae60"),
}


def _ms_to_hms(ms: int) -> str:
    total_s = ms // 1000
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    frac = (ms % 1000) // 10
    return f"{h:02d}:{m:02d}:{s:02d}.{frac:02d}"


class StatusTab(QWidget):
    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state

        layout = QFormLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setVerticalSpacing(8)

        self._connection_label = QLabel("NOT CONNECTED")
        self._player_label = QLabel("—")
        self._file_label = QLabel("—")
        self._file_label.setWordWrap(True)
        self._time_label = QLabel("—")

        layout.addRow("Connection:", self._connection_label)
        layout.addRow("Player:", self._player_label)
        layout.addRow("File:", self._file_label)
        layout.addRow("Time:", self._time_label)

        app_state.player_state_changed.connect(self._on_player_state_changed)
        self._refresh_player_label()

    def _refresh_player_label(self) -> None:
        cfg = self._app_state.config.player
        self._player_label.setText(
            f"{cfg.type}  ({cfg.host}:{cfg.port})"
        )

    def _on_player_state_changed(self, state: PlayerState) -> None:
        text, color = _STATE_LABELS.get(
            state.connection_state,
            ("UNKNOWN", "#7f8c8d"),
        )
        self._connection_label.setText(text)
        self._connection_label.setStyleSheet(f"color: {color}; font-weight: bold;")

        self._file_label.setText(state.file_path or "—")
        if state.connection_state != MediaConnectionState.NOT_CONNECTED:
            time_str = _ms_to_hms(state.current_time_ms)
            speed_str = f"{state.playback_speed:.2f}x"
            self._time_label.setText(f"{time_str}  ({speed_str} speed)")
        else:
            self._time_label.setText("—")
        self._refresh_player_label()
