"""MainWindow — tab container; close button minimises to tray."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QMainWindow, QTabWidget

_UI_REFRESH_INTERVAL_MS = 50  # 20 Hz


class MainWindow(QMainWindow):
    """Main application window with four tabs.

    Closing the window hides it (minimises to tray) instead of quitting.

    Live values are repainted from a UI timer that is independent of the
    output evaluation loop, so a slow device can never freeze the display.
    """

    def __init__(self, app_state, engine, output_manager, player_manager, data_logger, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("funscript-gateway")
        self.setMinimumSize(700, 450)

        from funscript_gateway.ui.inputs_tab import InputsTab
        from funscript_gateway.ui.outputs_tab import OutputsTab
        from funscript_gateway.ui.settings_tab import SettingsTab
        from funscript_gateway.ui.status_tab import StatusTab

        self._tabs = QTabWidget()
        self._inputs_tab = InputsTab(app_state, engine)
        self._outputs_tab = OutputsTab(app_state, output_manager)
        self._tabs.addTab(StatusTab(app_state), "Status")
        self._tabs.addTab(self._inputs_tab, "Inputs")
        self._tabs.addTab(self._outputs_tab, "Outputs")
        self._tabs.addTab(SettingsTab(app_state, player_manager, data_logger), "Settings")
        self.setCentralWidget(self._tabs)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(_UI_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._refresh_live_values)
        self._refresh_timer.start()

    def _refresh_live_values(self) -> None:
        # Only the visible tab needs repainting; skip entirely while in the tray.
        if not self.isVisible():
            return
        current = self._tabs.currentWidget()
        if current is self._inputs_tab:
            self._inputs_tab.refresh_values()
        elif current is self._outputs_tab:
            self._outputs_tab.refresh_values()

    def closeEvent(self, event: QEvent) -> None:
        """Hide to tray instead of closing."""
        event.ignore()
        self.hide()
