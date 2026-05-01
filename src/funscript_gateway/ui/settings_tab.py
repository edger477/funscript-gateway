"""Settings tab — player connection and funscript search path configuration."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from funscript_gateway.config import save_config
from funscript_gateway.models import PLAYER_DEFAULT_PORTS

logger = logging.getLogger(__name__)


class SettingsTab(QWidget):
    def __init__(self, app_state, player_manager, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._player_manager = player_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Player settings group
        player_group = QGroupBox("Player Settings")
        player_form = QFormLayout(player_group)

        self._type_combo = QComboBox()
        self._type_combo.addItems(["heresphere", "mpc_hc"])
        player_form.addRow("Player Type:", self._type_combo)

        self._host_edit = QLineEdit()
        player_form.addRow("Host:", self._host_edit)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        player_form.addRow("Port:", self._port_spin)

        self._poll_label = QLabel("Poll interval (ms):")
        self._poll_spin = QSpinBox()
        self._poll_spin.setRange(50, 5000)
        player_form.addRow(self._poll_label, self._poll_spin)

        self._autostart_check = QCheckBox("On start playing, start restim instances")
        player_form.addRow("", self._autostart_check)

        self._autostart_urls_edit = QLineEdit()
        self._autostart_urls_edit.setPlaceholderText(
            "http://localhost:12348/v1,http://localhost:12349/v1"
        )
        self._autostart_urls_edit.setToolTip(
            "Comma-separated restim base URLs. When playback starts and a restim instance\n"
            "is not playing, GET {url}/actions/start is called automatically."
        )
        player_form.addRow("Restim URLs:", self._autostart_urls_edit)

        self._autostart_check.toggled.connect(self._autostart_urls_edit.setEnabled)

        layout.addWidget(player_group)

        # Funscript paths group
        paths_group = QGroupBox("Funscript Paths")
        paths_layout = QVBoxLayout(paths_group)
        paths_layout.addWidget(QLabel("Additional search paths:"))

        self._paths_list = QListWidget()
        paths_layout.addWidget(self._paths_list)

        paths_buttons = QHBoxLayout()
        btn_add_path = QPushButton("+ Add path")
        btn_remove_path = QPushButton("- Remove")
        btn_add_path.clicked.connect(self._on_add_path)
        btn_remove_path.clicked.connect(self._on_remove_path)
        paths_buttons.addWidget(btn_add_path)
        paths_buttons.addWidget(btn_remove_path)
        paths_buttons.addStretch()
        paths_layout.addLayout(paths_buttons)

        layout.addWidget(paths_group)

        # Apply / Cancel buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_apply = QPushButton("Apply")
        btn_cancel = QPushButton("Cancel")
        btn_apply.clicked.connect(self._on_apply)
        btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(btn_apply)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)
        layout.addStretch()

        self._heresphere_host: str = "127.0.0.1"
        self._mpc_hc_host: str = "127.0.0.1"
        self._current_player_type: str = "heresphere"

        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._load_from_config()

    def _load_from_config(self) -> None:
        cfg = self._app_state.config.player
        self._heresphere_host = cfg.heresphere_host
        self._mpc_hc_host = cfg.mpc_hc_host
        self._current_player_type = cfg.type

        self._type_combo.blockSignals(True)
        self._type_combo.setCurrentText(cfg.type)
        self._type_combo.blockSignals(False)

        self._host_edit.setText(cfg.heresphere_host if cfg.type == "heresphere" else cfg.mpc_hc_host)
        self._port_spin.setValue(cfg.port)
        self._poll_spin.setValue(cfg.poll_interval_ms)
        self._autostart_check.setChecked(cfg.restim_autostart_enabled)
        self._autostart_urls_edit.setText(",".join(cfg.restim_autostart_urls))
        self._autostart_urls_edit.setEnabled(cfg.restim_autostart_enabled)
        self._on_type_changed(cfg.type)

        self._paths_list.clear()
        for p in self._app_state.config.funscript_search_paths:
            self._paths_list.addItem(p)

    def _on_type_changed(self, player_type: str) -> None:
        # Save the host currently shown in the edit to whichever type we're switching from,
        # then display the stored host for the new type.
        if self._current_player_type == "heresphere":
            self._heresphere_host = self._host_edit.text()
        else:
            self._mpc_hc_host = self._host_edit.text()
        self._host_edit.setText(
            self._heresphere_host if player_type == "heresphere" else self._mpc_hc_host
        )
        self._current_player_type = player_type

        visible = player_type == "mpc_hc"
        self._poll_label.setVisible(visible)
        self._poll_spin.setVisible(visible)
        # Auto-suggest the default port for the selected player type,
        # but only if the current port value matches a known default
        # (i.e. the user hasn't set a custom port).
        current_port = self._port_spin.value()
        if current_port in PLAYER_DEFAULT_PORTS.values():
            self._port_spin.setValue(PLAYER_DEFAULT_PORTS.get(player_type, current_port))

    def _on_add_path(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select funscript search path")
        if directory:
            self._paths_list.addItem(directory)

    def _on_remove_path(self) -> None:
        for item in self._paths_list.selectedItems():
            self._paths_list.takeItem(self._paths_list.row(item))

    def _on_apply(self) -> None:
        cfg = self._app_state.config.player
        old_type = cfg.type
        old_host = cfg.host
        old_port = cfg.port

        # Flush the currently displayed host into the right per-type tracker.
        if self._current_player_type == "heresphere":
            self._heresphere_host = self._host_edit.text().strip()
        else:
            self._mpc_hc_host = self._host_edit.text().strip()

        cfg.type = self._type_combo.currentText()
        cfg.heresphere_host = self._heresphere_host
        cfg.mpc_hc_host = self._mpc_hc_host
        cfg.port = self._port_spin.value()
        cfg.poll_interval_ms = self._poll_spin.value()
        cfg.restim_autostart_enabled = self._autostart_check.isChecked()
        cfg.restim_autostart_urls = [
            u.strip() for u in self._autostart_urls_edit.text().split(",") if u.strip()
        ]

        paths = []
        for i in range(self._paths_list.count()):
            paths.append(self._paths_list.item(i).text())
        self._app_state.config.funscript_search_paths = paths

        try:
            save_config(self._app_state.config)
        except Exception as exc:
            logger.error("Failed to save config: %s", exc)

        # Restart player manager if connection settings changed.
        player_settings_changed = (
            cfg.type != old_type
            or cfg.host != old_host
            or cfg.port != old_port
        )
        if player_settings_changed and self._player_manager is not None:
            import asyncio
            asyncio.ensure_future(self._restart_player())

    async def _restart_player(self) -> None:
        await self._player_manager.stop()
        await self._player_manager.start()

    def _on_cancel(self) -> None:
        self._load_from_config()
