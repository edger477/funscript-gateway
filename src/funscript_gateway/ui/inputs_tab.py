"""Inputs tab — manage all input sources (funscript axes, restim, calculated)."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from funscript_gateway.models import (
    ArithmeticInput,
    As5311Input,
    CalculatedInput,
    FunscriptAxisInput,
    RestimInput,
)

logger = logging.getLogger(__name__)

_COL_ENABLED = 0
_COL_TYPE = 1
_COL_NAME = 2
_COL_VALUE = 3
_COL_STATUS = 4
_COL_USED_IN = 5
_NUM_COLS = 6

_TYPE_LABELS = {
    "funscript": "Funscript Axis",
    "restim": "Restim",
    "calculated": "Calculated (Logical)",
    "arithmetic": "Calculated (Arithmetic)",
    "as5311": "AS5311",
}


def _input_type_key(inp) -> str:
    if isinstance(inp, FunscriptAxisInput):
        return "funscript"
    if isinstance(inp, RestimInput):
        return "restim"
    if isinstance(inp, CalculatedInput):
        return "calculated"
    if isinstance(inp, ArithmeticInput):
        return "arithmetic"
    if isinstance(inp, As5311Input):
        return "as5311"
    return "unknown"


class InputsTab(QWidget):
    def __init__(self, app_state, engine, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._engine = engine

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()

        btn_add = QPushButton("Add")
        btn_add.setToolTip("Add a new input")
        btn_add.clicked.connect(self._on_add)

        self._btn_edit = QPushButton("Edit")
        self._btn_edit.setEnabled(False)
        self._btn_edit.clicked.connect(self._on_edit)

        self._btn_remove = QPushButton("Remove")
        self._btn_remove.setEnabled(False)
        self._btn_remove.clicked.connect(self._on_remove)

        btn_refresh = QPushButton("Refresh")
        btn_refresh.setToolTip("Re-validate funscript axis files for the current video")
        btn_refresh.clicked.connect(self._on_refresh)

        toolbar.addWidget(btn_add)
        toolbar.addWidget(self._btn_edit)
        toolbar.addWidget(self._btn_remove)
        toolbar.addStretch()
        toolbar.addWidget(btn_refresh)
        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget(0, _NUM_COLS)
        self._table.setHorizontalHeaderLabels(
            ["En", "Type", "Name", "Value", "Status", "Used In"]
        )
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_COL_VALUE, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_USED_IN, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(_COL_VALUE, 120)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemDoubleClicked.connect(self._on_edit)
        layout.addWidget(self._table)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        app_state.inputs_updated.connect(self._on_inputs_updated)
        app_state.outputs_updated.connect(self._refresh_values)

        # Populate from already-loaded config (inputs_updated is not emitted at startup)
        if app_state.inputs:
            self._rebuild_table(app_state.inputs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _used_in_count(self, inp_name: str) -> int:
        count = 0
        for out in self._app_state.config.outputs:
            if out.input_name == inp_name:
                count += 1
        for inp in self._app_state.inputs:
            if isinstance(inp, CalculatedInput):
                for entry in inp.entries:
                    if entry.input_name == inp_name:
                        count += 1
                        break
            elif isinstance(inp, ArithmeticInput):
                for entry in inp.entries:
                    if entry.input_name == inp_name:
                        count += 1
                        break
        return count

    def _primary_input_names(self) -> list[str]:
        """Names of non-derived inputs (for Logical dialog)."""
        return [
            inp.name for inp in self._app_state.inputs
            if not isinstance(inp, (CalculatedInput, ArithmeticInput))
        ]

    def _non_arithmetic_names(self) -> list[str]:
        """Names of all inputs except ArithmeticInput (for Arithmetic dialog)."""
        return [
            inp.name for inp in self._app_state.inputs
            if not isinstance(inp, ArithmeticInput)
        ]

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_inputs_updated(self, inputs: list) -> None:
        self._rebuild_table(inputs)

    def _on_selection_changed(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        has_sel = bool(rows)
        self._btn_edit.setEnabled(has_sel and len(rows) == 1)
        # Remove only if selected and "used in" == 0 for all selected
        can_remove = has_sel
        if can_remove:
            inputs = self._app_state.inputs
            for row in rows:
                if row < len(inputs):
                    inp = inputs[row]
                    if self._used_in_count(inp.name) > 0:
                        can_remove = False
                        break
        self._btn_remove.setEnabled(can_remove)

    # ------------------------------------------------------------------
    # Table building
    # ------------------------------------------------------------------

    def _rebuild_table(self, inputs: list) -> None:
        self._table.setRowCount(0)
        for row, inp in enumerate(inputs):
            self._table.insertRow(row)
            self._set_row(row, inp)

    def _set_row(self, row: int, inp) -> None:
        # Enabled checkbox
        en_item = QTableWidgetItem()
        en_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        en_item.setCheckState(
            Qt.CheckState.Checked if inp.enabled else Qt.CheckState.Unchecked
        )
        self._table.setItem(row, _COL_ENABLED, en_item)

        # Type
        type_key = _input_type_key(inp)
        self._table.setItem(row, _COL_TYPE, QTableWidgetItem(_TYPE_LABELS.get(type_key, type_key)))

        # Name
        name_item = QTableWidgetItem(inp.name)
        self._table.setItem(row, _COL_NAME, name_item)

        # Value widget + Status text
        if isinstance(inp, FunscriptAxisInput):
            bar = QProgressBar()
            bar.setRange(0, 100)
            val = inp.current_value
            bar.setValue(int(val))
            bar.setFormat(f"{val:.1f}")
            self._table.setCellWidget(row, _COL_VALUE, bar)

            if inp.file_missing:
                if inp.file_path:
                    status = QTableWidgetItem("File missing")
                    status.setForeground(Qt.GlobalColor.darkYellow)
                else:
                    status = QTableWidgetItem(f"No file (default {inp.default_value:.2f})")
                    status.setForeground(Qt.GlobalColor.darkGray)
            elif not inp.actions:
                status = QTableWidgetItem("Not loaded")
            else:
                status = QTableWidgetItem("OK")
            self._table.setItem(row, _COL_STATUS, status)

        elif isinstance(inp, RestimInput):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(inp.current_value))
            bar.setFormat("ON" if inp.current_value >= 50.0 else "OFF")
            self._table.setCellWidget(row, _COL_VALUE, bar)

            if inp.is_error:
                default_txt = "on" if inp.default_value else "off"
                status = QTableWidgetItem(f"Error (default {default_txt})")
                status.setForeground(Qt.GlobalColor.darkRed)
            else:
                status = QTableWidgetItem("OK")
            self._table.setItem(row, _COL_STATUS, status)

        elif isinstance(inp, CalculatedInput):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(inp.current_value))
            bar.setFormat("ON" if inp.current_value >= 50.0 else "OFF")
            self._table.setCellWidget(row, _COL_VALUE, bar)
            n = len(inp.entries)
            self._table.setItem(row, _COL_STATUS, QTableWidgetItem(f"{n} entr{'y' if n == 1 else 'ies'}"))

        elif isinstance(inp, ArithmeticInput):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(inp.current_value))
            bar.setFormat(f"{inp.current_value:.1f}")
            self._table.setCellWidget(row, _COL_VALUE, bar)
            n = len(inp.entries)
            total_w = sum(e.multiplier for e in inp.entries)
            self._table.setItem(
                row, _COL_STATUS,
                QTableWidgetItem(f"{n} entr{'y' if n == 1 else 'ies'}, ÷{total_w}"),
            )

        elif isinstance(inp, As5311Input):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(inp.current_value))
            bar.setFormat(f"{inp.last_position_mm:.3f} mm")
            self._table.setCellWidget(row, _COL_VALUE, bar)
            if inp.is_error:
                status = QTableWidgetItem("Error")
                status.setForeground(Qt.GlobalColor.darkRed)
            else:
                hi = inp.threshold_mm + inp.range_mm
                status = QTableWidgetItem(f"{inp.threshold_mm:.3g}–{hi:.4g} mm")
            self._table.setItem(row, _COL_STATUS, status)

        # Used In
        used = self._used_in_count(inp.name)
        used_item = QTableWidgetItem(str(used) if used > 0 else "—")
        used_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if used > 0:
            used_item.setToolTip(f"Referenced by {used} output(s)/input(s)")
        self._table.setItem(row, _COL_USED_IN, used_item)

    def _refresh_values(self) -> None:
        """Update value bars without rebuilding the whole table (called at 20 Hz)."""
        inputs = self._app_state.inputs
        for row, inp in enumerate(inputs):
            if row >= self._table.rowCount():
                break
            bar = self._table.cellWidget(row, _COL_VALUE)
            if bar is None:
                continue
            val = inp.current_value
            bar.setValue(int(val))
            if isinstance(inp, FunscriptAxisInput):
                bar.setFormat(f"{val:.1f}")
            elif isinstance(inp, ArithmeticInput):
                bar.setFormat(f"{val:.1f}")
            elif isinstance(inp, As5311Input):
                bar.setFormat(f"{inp.last_position_mm:.3f} mm")
            else:
                bar.setFormat("ON" if val >= 50.0 else "OFF")

            # Refresh status for types whose error state can change at runtime
            if isinstance(inp, RestimInput):
                item = self._table.item(row, _COL_STATUS)
                if item:
                    if inp.is_error:
                        default_txt = "on" if inp.default_value else "off"
                        item.setText(f"Error (default {default_txt})")
                        item.setForeground(Qt.GlobalColor.darkRed)
                    else:
                        item.setText("OK")
                        item.setForeground(self._table.palette().text().color())

            elif isinstance(inp, As5311Input):
                item = self._table.item(row, _COL_STATUS)
                if item:
                    if inp.is_error:
                        item.setText("Error")
                        item.setForeground(Qt.GlobalColor.darkRed)
                    else:
                        hi = inp.threshold_mm + inp.range_mm
                        item.setText(f"{inp.threshold_mm:.3g}–{hi:.4g} mm")
                        item.setForeground(self._table.palette().text().color())

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        file_path = self._app_state.player_state.file_path
        if file_path:
            self._engine.discover(file_path)

    def _on_add(self) -> None:
        menu = QMenu(self)
        menu.addAction("Funscript Axis", self._add_funscript_axis)
        menu.addAction("Restim", self._add_restim)
        menu.addAction("AS5311 Sensor", self._add_as5311)
        menu.addAction("Calculated - Logical", self._add_calculated)
        menu.addAction("Calculated - Arithmetic", self._add_arithmetic)
        btn = self.sender()
        pos = btn.mapToGlobal(btn.rect().bottomLeft()) if btn else self.cursor().pos()
        menu.exec(pos)

    def _add_funscript_axis(self) -> None:
        from funscript_gateway.ui.input_dialogs import FunscriptAxisDialog
        dlg = FunscriptAxisDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        inp = dlg.get_config()
        if not inp.name:
            QMessageBox.warning(self, "Invalid", "Axis name cannot be empty.")
            return
        self._save_new_input(inp)

    def _add_restim(self) -> None:
        from funscript_gateway.ui.input_dialogs import RestimDialog
        dlg = RestimDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        inp = dlg.get_config()
        if not inp.name:
            QMessageBox.warning(self, "Invalid", "Input name cannot be empty.")
            return
        self._save_new_input(inp)

    def _add_as5311(self) -> None:
        from funscript_gateway.ui.input_dialogs import As5311Dialog
        dlg = As5311Dialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        inp = dlg.get_config()
        if not inp.name:
            QMessageBox.warning(self, "Invalid", "Input name cannot be empty.")
            return
        self._save_new_input(inp)

    def _add_arithmetic(self) -> None:
        available = self._non_arithmetic_names()
        if not available:
            QMessageBox.information(
                self, "Arithmetic Input",
                "You need at least 1 non-arithmetic input before creating an arithmetic one."
            )
            return
        from funscript_gateway.ui.input_dialogs import ArithmeticDialog
        dlg = ArithmeticDialog(available_inputs=available, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        inp = dlg.get_config()
        if not inp.name:
            QMessageBox.warning(self, "Invalid", "Input name cannot be empty.")
            return
        if not inp.entries:
            QMessageBox.warning(self, "Invalid", "An arithmetic input needs at least 1 entry.")
            return
        self._save_new_input(inp)

    def _add_calculated(self) -> None:
        non_calc = self._primary_input_names()
        if not non_calc:
            QMessageBox.information(
                self, "Calculated Input",
                "You need at least 1 non-calculated input before creating a calculated one."
            )
            return
        from funscript_gateway.ui.input_dialogs import CalculatedDialog
        dlg = CalculatedDialog(available_inputs=non_calc, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        inp = dlg.get_config()
        if not inp.name:
            QMessageBox.warning(self, "Invalid", "Input name cannot be empty.")
            return
        if not inp.entries:
            QMessageBox.warning(self, "Invalid", "A calculated input needs at least 1 entry.")
            return
        self._save_new_input(inp)

    def _edit_arithmetic(self, row: int, inp: ArithmeticInput) -> None:
        available = self._non_arithmetic_names()
        from funscript_gateway.ui.input_dialogs import ArithmeticDialog
        dlg = ArithmeticDialog(available_inputs=available, config=inp, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_inp = dlg.get_config()
        if not new_inp.entries:
            QMessageBox.warning(self, "Invalid", "An arithmetic input needs at least 1 entry.")
            return
        self._replace_input(row, inp, new_inp)

    def _save_new_input(self, inp) -> None:
        self._app_state.inputs.append(inp)  # config.inputs is the same list
        self._persist_and_emit()

    def _on_edit(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if not rows:
            return
        row = rows[0]
        inputs = self._app_state.inputs
        if row >= len(inputs):
            return
        inp = inputs[row]

        if isinstance(inp, FunscriptAxisInput):
            from funscript_gateway.ui.input_dialogs import FunscriptAxisDialog
            dlg = FunscriptAxisDialog(config=inp, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            new_inp = dlg.get_config()
            new_inp.file_path = inp.file_path
            new_inp.actions = inp.actions
            new_inp.current_value = inp.current_value
            new_inp.file_missing = inp.file_missing
            self._replace_input(row, inp, new_inp)

        elif isinstance(inp, RestimInput):
            from funscript_gateway.ui.input_dialogs import RestimDialog
            dlg = RestimDialog(config=inp, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            new_inp = dlg.get_config()
            self._replace_input(row, inp, new_inp)

        elif isinstance(inp, ArithmeticInput):
            self._edit_arithmetic(row, inp)
            return

        elif isinstance(inp, CalculatedInput):
            non_calc = self._primary_input_names()
            from funscript_gateway.ui.input_dialogs import CalculatedDialog
            dlg = CalculatedDialog(available_inputs=non_calc, config=inp, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            new_inp = dlg.get_config()
            if not new_inp.entries:
                QMessageBox.warning(self, "Invalid", "A calculated input needs at least 1 entry.")
                return
            self._replace_input(row, inp, new_inp)

        elif isinstance(inp, As5311Input):
            from funscript_gateway.ui.input_dialogs import As5311Dialog
            dlg = As5311Dialog(config=inp, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            new_inp = dlg.get_config()
            self._replace_input(row, inp, new_inp)

    def _replace_input(self, row: int, old_inp, new_inp) -> None:
        self._app_state.inputs[row] = new_inp  # config.inputs is the same list
        self._persist_and_emit()

    def _on_remove(self) -> None:
        rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()}, reverse=True
        )
        inputs = self._app_state.inputs  # same as config.inputs
        for row in rows:
            if 0 <= row < len(inputs):
                if self._used_in_count(inputs[row].name) > 0:
                    continue
                inputs.pop(row)
        self._persist_and_emit()

    def _persist_and_emit(self) -> None:
        from funscript_gateway.config import save_config
        try:
            save_config(self._app_state.config)
        except Exception as exc:
            logger.warning("Failed to save config after input change: %s", exc)
        self._app_state.inputs_updated.emit(self._app_state.inputs)
