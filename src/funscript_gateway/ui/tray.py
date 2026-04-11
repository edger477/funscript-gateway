"""System tray icon with two visual states (playing / not playing)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from funscript_gateway.models import MediaConnectionState, PlayerState


def _make_icon(color: str) -> QPixmap:
    """Create a 16x16 solid-color square icon programmatically."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, 14, 14)
    painter.end()
    return pixmap


class SystemTrayIcon(QSystemTrayIcon):
    """System tray icon for funscript-gateway.

    Menu: Open | --- | Quit
    Double-click shows main window.
    Icon state: green (playing) / grey (not playing).
    """

    def __init__(self, main_window, app_state, parent=None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._app_state = app_state

        self._icon_active = _make_icon("#27ae60")
        self._icon_inactive = _make_icon("#7f8c8d")

        self.setIcon(self._icon_inactive)
        self.setToolTip("funscript-gateway")

        self._build_menu()
        self.activated.connect(self._on_activated)
        app_state.player_state_changed.connect(self._on_player_state_changed)

    def _build_menu(self) -> None:
        menu = QMenu()
        open_action = QAction("Open funscript-gateway", self)
        open_action.triggered.connect(self._show_window)
        menu.addAction(open_action)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)
        self.setContextMenu(menu)

    def _show_window(self) -> None:
        self._main_window.showNormal()
        self._main_window.raise_()
        self._main_window.activateWindow()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _on_player_state_changed(self, state: PlayerState) -> None:
        if state.connection_state == MediaConnectionState.CONNECTED_AND_PLAYING:
            self.setIcon(self._icon_active)
            self.setToolTip("funscript-gateway — Playing")
        else:
            self.setIcon(self._icon_inactive)
            self.setToolTip("funscript-gateway")
