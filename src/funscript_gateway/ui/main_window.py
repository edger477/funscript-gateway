"""MainWindow — tab container; close button minimises to tray."""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QMainWindow, QTabWidget


class MainWindow(QMainWindow):
    """Main application window with four tabs.

    Closing the window hides it (minimises to tray) instead of quitting.
    """

    def __init__(self, app_state, engine, output_manager, player_manager, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("funscript-gateway")
        self.setMinimumSize(700, 450)

        from funscript_gateway.ui.axes_tab import AxesTab
        from funscript_gateway.ui.outputs_tab import OutputsTab
        from funscript_gateway.ui.settings_tab import SettingsTab
        from funscript_gateway.ui.status_tab import StatusTab

        tabs = QTabWidget()
        tabs.addTab(StatusTab(app_state), "Status")
        tabs.addTab(AxesTab(app_state, engine), "Axes")
        tabs.addTab(OutputsTab(app_state, output_manager), "Outputs")
        tabs.addTab(SettingsTab(app_state, player_manager), "Settings")
        self.setCentralWidget(tabs)

    def closeEvent(self, event: QEvent) -> None:
        """Hide to tray instead of closing."""
        event.ignore()
        self.hide()
