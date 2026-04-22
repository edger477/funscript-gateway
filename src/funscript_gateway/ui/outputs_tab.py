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
        app_state.outputs_updated.connect(self._refresh_table)

    def _on_selection_changed(self) -> None:
        has_selection = bool(self._table.selectedIndexes())
        self._btn_edit.setEnabled(has_selection)
        self._btn_remove.setEnabled(has_selection)

    def _refresh_table(self) -> None:
        outputs = self._app_state.outputs
        if self._table.rowCount() != len(outputs):
            self._table.setRowCount(len(outputs))
        for row, instance in enumerate(outputs):
            self._update_row(row, instance)

    def _update_row(self, row: int, instance: OutputInstance) -> None:
        cfg = instance.config

        enabled_item = QTableWidgetItem()
        enabled_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        enabled_item.setCheckState(
            Qt.CheckState.Checked if cfg.enabled else Qt.CheckState.Unchecked
        )
        self._table.setItem(row, _COL_ENABLED, enabled_item)
        self._table.setItem(row, _COL_NAME, QTableWidgetItem(cfg.name))
        self._table.setItem(
            row, _COL_TYPE, QTableWidgetItem(_TYPE_LABELS.get(cfg.type, cfg.type))
        )
        self._table.setItem(row, _COL_INPUT_NAME, QTableWidgetItem(cfg.input_name))
        self._table.setItem(
            row, _COL_INPUT, QTableWidgetItem(f"{instance.last_input_value:.1f}")
        )

        state_text = "ON" if instance.last_output_state else "OFF"
        state_item = QTableWidgetItem(state_text)
        if instance.is_degraded:
            state_item.setForeground(Qt.GlobalColor.darkYellow)
        elif instance.last_output_state:
            state_item.setForeground(Qt.GlobalColor.darkGreen)
        else:
            state_item.setForeground(Qt.GlobalColor.darkGray)
        self._table.setItem(row, _COL_STATE, state_item)

    def _input_names(self) -> list[str]:
        return [inp.name for inp in self._app_state.inputs]

    def _on_add(self) -> None:
        dlg = OutputDialog(self._input_names(), parent=self)
        if dlg.exec() == OutputDialog.DialogCode.Accepted:
            new_cfg = dlg.get_config()
            self._app_state.config.outputs.append(new_cfg)
            self._rebuild_outputs()

    def _on_edit(self) -> None:
        selected_rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if not selected_rows:
            return
        row = selected_rows[0]
        outputs = self._app_state.outputs
        if row >= len(outputs):
            return
        existing_cfg = outputs[row].config
        dlg = OutputDialog(self._input_names(), config=existing_cfg, parent=self)
        if dlg.exec() == OutputDialog.DialogCode.Accepted:
            new_cfg = dlg.get_config()
            self._app_state.config.outputs[row] = new_cfg
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
        import asyncio

        try:
            save_config(self._app_state.config)
        except Exception as exc:
            logger.warning("Failed to save config after output change: %s", exc)

        if self._output_manager is not None:
            asyncio.ensure_future(self._output_manager.reload_outputs())
