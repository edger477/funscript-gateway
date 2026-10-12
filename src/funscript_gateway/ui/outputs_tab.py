"""Outputs tab — displays configured outputs with live state indicators."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from funscript_gateway.models import OutputInstance
from funscript_gateway.ui.output_dialog import OutputDialog

_COL_ENABLED = 0
_COL_NAME = 1
_COL_TYPE = 2
_COL_INPUT_NAME = 3
_COL_INPUT = 4
_COL_STATE = 5
_NUM_COLS = 6

_TYPE_LABELS = {
    "threshold_tasmota": "Threshold → Tasmota",
    "threshold_mqtt": "Threshold → MQTT",
    "ws_value": "Value → WebSocket",
}


class OutputsTab(QWidget):
    def __init__(self, app_state, output_manager, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._output_manager = output_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        btn_add = QPushButton("Add")
        self._btn_edit = QPushButton("Edit")
        self._btn_remove = QPushButton("Remove")
        self._btn_edit.setEnabled(False)
        self._btn_remove.setEnabled(False)
        btn_add.clicked.connect(self._on_add)
        self._btn_edit.clicked.connect(self._on_edit)
        self._btn_remove.clicked.connect(self._on_remove)
        toolbar.addWidget(btn_add)
        toolbar.addWidget(self._btn_edit)
        toolbar.addWidget(self._btn_remove)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget(0, _NUM_COLS)
        self._table.setHorizontalHeaderLabels(
            ["Enabled", "Name", "Type", "Input", "Value", "State"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_NAME, QHeaderView.ResizeMode.Stretch
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        # Structural changes rebuild the rows; live values are refreshed by
        # MainWindow's UI timer via refresh_values().
        app_state.outputs_updated.connect(self._rebuild_table)
        self._rebuild_table()

    def _on_selection_changed(self) -> None:
        has_selection = bool(self._table.selectedIndexes())
        self._btn_edit.setEnabled(has_selection)
        self._btn_remove.setEnabled(has_selection)

    def _rebuild_table(self) -> None:
        """Create one row of items per output (on startup and after reloads)."""
        outputs = self._app_state.outputs
        self._table.setRowCount(len(outputs))
        for row, instance in enumerate(outputs):
            cfg = instance.config
            enabled_item = QTableWidgetItem()
            # Display only: toggling here has no handler, so don't offer it.
            enabled_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            enabled_item.setCheckState(
                Qt.CheckState.Checked if cfg.enabled else Qt.CheckState.Unchecked
            )
            self._table.setItem(row, _COL_ENABLED, enabled_item)
            self._table.setItem(row, _COL_NAME, QTableWidgetItem(cfg.name))
            self._table.setItem(
                row, _COL_TYPE, QTableWidgetItem(_TYPE_LABELS.get(cfg.type, cfg.type))
            )
            self._table.setItem(row, _COL_INPUT_NAME, QTableWidgetItem(cfg.input_name))
            self._table.setItem(row, _COL_INPUT, QTableWidgetItem())
            self._table.setItem(row, _COL_STATE, QTableWidgetItem())
        self.refresh_values()

    def refresh_values(self) -> None:
        """Update the live Value/State cells in place (called at 20 Hz)."""
        outputs = self._app_state.outputs
        if self._table.rowCount() != len(outputs):
            self._rebuild_table()
            return
        for row, instance in enumerate(outputs):
            self._update_row(row, instance)

    def _update_row(self, row: int, instance: OutputInstance) -> None:
        cfg = instance.config
        input_item = self._table.item(row, _COL_INPUT)
        state_item = self._table.item(row, _COL_STATE)
        if input_item is None or state_item is None:
            return
        input_item.setText(f"{instance.last_input_value:.1f}")

        if instance.driver is None:
            state_item.setText("INACTIVE")
            state_item.setToolTip("Driver could not be created (see log); edit or reload to retry.")
            state_item.setForeground(Qt.GlobalColor.darkRed)
        elif cfg.type == "ws_value":
            ws = cfg.ws
            span = ws.max_output - ws.min_output
            out_val = ws.min_output + span * instance.last_input_value / 100.0
            state_item.setText(f"{out_val:.2f}")
            state_item.setForeground(Qt.GlobalColor.darkCyan)
        else:
            state_item.setText("ON" if instance.last_output_state else "OFF")
            if instance.is_degraded:
                state_item.setForeground(Qt.GlobalColor.darkYellow)
            elif instance.last_output_state:
                state_item.setForeground(Qt.GlobalColor.darkGreen)
            else:
                state_item.setForeground(Qt.GlobalColor.darkGray)

    def _input_names(self) -> list[str]:
        return [inp.name for inp in self._app_state.inputs]

    def _run_dialog(self, config=None):
        """Run the output dialog; return the new config if accepted, else None."""
        dlg = OutputDialog(self._input_names(), config=config, parent=self)
        try:
            if dlg.exec() != OutputDialog.DialogCode.Accepted:
                return None
            return dlg.get_config()
        finally:
            dlg.deleteLater()  # parented to the tab — would otherwise live forever

    def _on_add(self) -> None:
        new_cfg = self._run_dialog()
        if new_cfg is not None:
            self._app_state.config.outputs.append(new_cfg)
            self._rebuild_outputs()

    def _on_edit(self) -> None:
        selected_rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if not selected_rows:
            return
        row = selected_rows[0]
        # app_state.outputs is index-aligned with config.outputs (one instance
        # per config entry, even when its driver failed), so rows map directly.
        configs = self._app_state.config.outputs
        if row >= len(configs):
            return
        new_cfg = self._run_dialog(configs[row])
        if new_cfg is not None:
            configs[row] = new_cfg
            self._rebuild_outputs()

    def _on_remove(self) -> None:
        selected_rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()}, reverse=True
        )
        if not selected_rows:
            return
        for row in selected_rows:
            if 0 <= row < len(self._app_state.config.outputs):
                self._app_state.config.outputs.pop(row)
        self._rebuild_outputs()

    def _rebuild_outputs(self) -> None:
        """Persist config change and ask the OutputManager to reload all drivers."""
        from funscript_gateway.config import save_config
        from funscript_gateway.tasks import spawn

        try:
            save_config(self._app_state.config)
        except Exception as exc:
            logger.warning("Failed to save config after output change: %s", exc)

        if self._output_manager is not None:
            spawn(self._output_manager.reload_outputs(), "reload outputs")
