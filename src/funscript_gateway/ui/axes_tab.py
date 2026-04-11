"""Axes tab — displays all loaded funscript axes with live value bars."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from funscript_gateway.funscript import parser
from funscript_gateway.models import FunscriptAxis

_COL_ENABLED = 0
_COL_NAME = 1
_COL_FILE = 2
_COL_VALUE = 3
_COL_STATUS = 4
_NUM_COLS = 5


class AxesTab(QWidget):
    def __init__(self, app_state, engine, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._engine = engine

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        btn_refresh = QPushButton("Refresh")
        btn_add = QPushButton("Add Axis")
        self._btn_remove = QPushButton("Remove Selected")
        self._btn_remove.setEnabled(False)
        btn_refresh.clicked.connect(self._on_refresh)
        btn_add.clicked.connect(self._on_add)
        self._btn_remove.clicked.connect(self._on_remove)
        toolbar.addWidget(btn_refresh)
        toolbar.addWidget(btn_add)
        toolbar.addWidget(self._btn_remove)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget(0, _NUM_COLS)
        self._table.setHorizontalHeaderLabels(
            ["Enabled", "Name", "File", "Value", "Status"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_FILE, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_VALUE, QHeaderView.ResizeMode.Fixed
        )
        self._table.setColumnWidth(_COL_VALUE, 140)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        self._table.itemSelectionChanged.connect(
            lambda: self._btn_remove.setEnabled(bool(self._table.selectedIndexes()))
        )
        app_state.axes_updated.connect(self._on_axes_updated)
        app_state.outputs_updated.connect(self._refresh_values)

    def _on_axes_updated(self, axes: list) -> None:
        self._rebuild_table(axes)

    def _rebuild_table(self, axes: list[FunscriptAxis]) -> None:
        self._table.setRowCount(0)
        for row, axis in enumerate(axes):
            self._table.insertRow(row)
            self._set_row(row, axis)

    def _set_row(self, row: int, axis: FunscriptAxis) -> None:
        # Enabled checkbox
        enabled_item = QTableWidgetItem()
        enabled_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        enabled_item.setCheckState(
            Qt.CheckState.Checked if axis.enabled else Qt.CheckState.Unchecked
        )
        self._table.setItem(row, _COL_ENABLED, enabled_item)

        # Name
        self._table.setItem(row, _COL_NAME, QTableWidgetItem(axis.name))

        # File (truncated; tooltip shows full path)
        file_item = QTableWidgetItem(os.path.basename(axis.file_path))
        file_item.setToolTip(axis.file_path)
        self._table.setItem(row, _COL_FILE, file_item)

        # Value bar
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(axis.current_value))
        bar.setFormat(f"{axis.current_value:.1f}")
        self._table.setCellWidget(row, _COL_VALUE, bar)

        # Status
        if axis.file_missing:
            status_item = QTableWidgetItem("File missing")
            status_item.setForeground(Qt.GlobalColor.darkYellow)
        elif not axis.actions:
            status_item = QTableWidgetItem("Not loaded")
        else:
            status_item = QTableWidgetItem("OK")
        self._table.setItem(row, _COL_STATUS, status_item)

        # Highlight missing file rows
        if axis.file_missing:
            for col in range(_NUM_COLS):
                item = self._table.item(row, col)
                if item:
                    item.setBackground(Qt.GlobalColor.yellow)

    def _refresh_values(self) -> None:
        axes = self._app_state.axes
        for row, axis in enumerate(axes):
            if row >= self._table.rowCount():
                break
            bar = self._table.cellWidget(row, _COL_VALUE)
            if bar:
                val = axis.current_value
                bar.setValue(int(val))
                bar.setFormat(f"{val:.1f}")

    def _on_refresh(self) -> None:
        file_path = self._app_state.player_state.file_path
        if file_path:
            self._engine.discover(file_path)

    def _on_add(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Axis", "Axis name:")
        if not ok or not name.strip():
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select funscript file", "", "Funscript (*.funscript);;All files (*)"
        )
        if not file_path:
            return
        actions = parser.load(file_path)
        axis = FunscriptAxis(
            name=name.strip(),
            file_path=file_path,
            enabled=True,
            actions=actions,
            file_missing=(not actions),
        )
        self._app_state.axes.append(axis)
        self._app_state.axes_updated.emit(self._app_state.axes)

    def _on_remove(self) -> None:
        selected_rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()}, reverse=True
        )
        axes = self._app_state.axes
        for row in selected_rows:
            if 0 <= row < len(axes):
                axes.pop(row)
        self._app_state.axes_updated.emit(axes)
