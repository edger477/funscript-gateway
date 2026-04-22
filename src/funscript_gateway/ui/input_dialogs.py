"""Dialogs for adding/editing each input type."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from funscript_gateway.models import (
    As5311Input,
    CalculatedEntry,
    CalculatedInput,
    FunscriptAxisInput,
    RestimCondition,
    RestimInput,
)


# ---------------------------------------------------------------------------
# FunscriptAxis dialog
# ---------------------------------------------------------------------------

class FunscriptAxisDialog(QDialog):
    """Dialog for creating/editing a FunscriptAxisInput."""

    def __init__(self, config: FunscriptAxisInput | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Funscript Axis Input")
        self.setMinimumWidth(340)

        cfg = config or FunscriptAxisInput(name="")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit(cfg.name)
        form.addRow("Axis name:", self._name_edit)

        hint = QLabel(
            "<small>File pattern: <i>{video}.{name}.funscript</i></small>"
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        form.addRow("", hint)

        self._default_spin = QDoubleSpinBox()
        self._default_spin.setRange(0.0, 1.0)
        self._default_spin.setDecimals(3)
        self._default_spin.setSingleStep(0.1)
        self._default_spin.setValue(cfg.default_value)
        self._default_spin.setToolTip(
            "Value used (0–1 mapped to 0–100) when the axis file is not found for the current video."
        )
        form.addRow("Default value (0–1):", self._default_spin)

        self._enabled_check = QCheckBox()
        self._enabled_check.setChecked(cfg.enabled)
        form.addRow("Enabled:", self._enabled_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_config(self) -> FunscriptAxisInput:
        return FunscriptAxisInput(
            name=self._name_edit.text().strip(),
            enabled=self._enabled_check.isChecked(),
            default_value=self._default_spin.value(),
        )


# ---------------------------------------------------------------------------
# Restim dialog
# ---------------------------------------------------------------------------

class RestimDialog(QDialog):
    """Dialog for creating/editing a RestimInput."""

    def __init__(self, config: RestimInput | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Restim HTTP Input")
        self.setMinimumWidth(400)

        cfg = config or RestimInput(name="")
        cond = cfg.condition

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit(cfg.name)
        form.addRow("Name:", self._name_edit)

        self._url_edit = QLineEdit(cfg.url)
        form.addRow("Endpoint URL:", self._url_edit)

        self._poll_spin = QDoubleSpinBox()
        self._poll_spin.setRange(0.1, 60.0)
        self._poll_spin.setDecimals(1)
        self._poll_spin.setSuffix(" s")
        self._poll_spin.setValue(cfg.poll_interval_s)
        form.addRow("Poll interval:", self._poll_spin)

        self._default_combo = QComboBox()
        self._default_combo.addItems(["off", "on"])
        self._default_combo.setCurrentIndex(1 if cfg.default_value else 0)
        self._default_combo.setToolTip("State used when the endpoint is unreachable.")
        form.addRow("Default (unavailable):", self._default_combo)

        self._enabled_check = QCheckBox()
        self._enabled_check.setChecked(cfg.enabled)
        form.addRow("Enabled:", self._enabled_check)

        layout.addLayout(form)

        # Conditions group
        cond_group = QGroupBox("Conditions (all enabled conditions must be met)")
        cond_form = QFormLayout(cond_group)

        self._playing_combo = QComboBox()
        self._playing_combo.addItems(["any", "yes", "no"])
        self._playing_combo.setCurrentText(cond.playing)
        cond_form.addRow("Playing:", self._playing_combo)

        self._vol_ui_check, self._vol_ui_dir, self._vol_ui_thresh = \
            self._build_threshold_row(
                cond_form, "Volume UI:",
                cond.volume_ui_enabled, cond.volume_ui_above, cond.volume_ui_threshold
            )

        self._vol_dev_check, self._vol_dev_dir, self._vol_dev_thresh = \
            self._build_threshold_row(
                cond_form, "Volume device:",
                cond.volume_device_enabled, cond.volume_device_above, cond.volume_device_threshold
            )

        layout.addWidget(cond_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _build_threshold_row(
        form: QFormLayout,
        label: str,
        enabled: bool,
        above: bool,
        threshold: float,
    ) -> tuple[QCheckBox, QComboBox, QDoubleSpinBox]:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)

        check = QCheckBox()
        check.setChecked(enabled)

        direction = QComboBox()
        direction.addItems(["above", "below"])
        direction.setCurrentIndex(0 if above else 1)
        direction.setEnabled(enabled)

        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1.0)
        spin.setDecimals(3)
        spin.setSingleStep(0.05)
        spin.setValue(threshold)
        spin.setEnabled(enabled)

        check.toggled.connect(direction.setEnabled)
        check.toggled.connect(spin.setEnabled)

        h.addWidget(check)
        h.addWidget(direction)
        h.addWidget(spin)
        form.addRow(label, row)
        return check, direction, spin

    def get_config(self) -> RestimInput:
        return RestimInput(
            name=self._name_edit.text().strip(),
            url=self._url_edit.text().strip(),
            enabled=self._enabled_check.isChecked(),
            poll_interval_s=self._poll_spin.value(),
            default_value=(self._default_combo.currentIndex() == 1),
            condition=RestimCondition(
                playing=self._playing_combo.currentText(),
                volume_ui_enabled=self._vol_ui_check.isChecked(),
                volume_ui_above=(self._vol_ui_dir.currentText() == "above"),
                volume_ui_threshold=self._vol_ui_thresh.value(),
                volume_device_enabled=self._vol_dev_check.isChecked(),
                volume_device_above=(self._vol_dev_dir.currentText() == "above"),
                volume_device_threshold=self._vol_dev_thresh.value(),
            ),
        )


# ---------------------------------------------------------------------------
# Calculated dialog
# ---------------------------------------------------------------------------

class CalculatedDialog(QDialog):
    """Dialog for creating/editing a CalculatedInput.

    Entries are shown as a vertical list.  The first entry has no operator.
    Subsequent entries show an operator selector before the input name.
    The formula label updates live as entries are added/modified.
    """

    def __init__(
        self,
        available_inputs: list[str],
        config: CalculatedInput | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Calculated Input")
        self.setMinimumWidth(480)

        cfg = config or CalculatedInput(name="")
        self._available = [n for n in available_inputs]  # names of non-calculated inputs

        layout = QVBoxLayout(self)

        top_form = QFormLayout()
        self._name_edit = QLineEdit(cfg.name)
        top_form.addRow("Name:", self._name_edit)

        self._enabled_check = QCheckBox()
        self._enabled_check.setChecked(cfg.enabled)
        top_form.addRow("Enabled:", self._enabled_check)
        layout.addLayout(top_form)

        # Formula label
        self._formula_label = QLabel()
        self._formula_label.setWordWrap(True)
        self._formula_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._formula_label)

        # Entry rows container
        self._entries_widget = QWidget()
        self._entries_layout = QVBoxLayout(self._entries_widget)
        self._entries_layout.setContentsMargins(0, 0, 0, 0)
        self._entries_layout.setSpacing(4)
        layout.addWidget(self._entries_widget)

        # Rows: list of (operator_combo | None, input_combo, remove_btn)
        self._rows: list[tuple] = []

        for entry in cfg.entries:
            self._add_row(entry.input_name, entry.operator)
        if not self._rows:
            self._add_row("", "and")

        add_btn = QPushButton("Add Entry")
        add_btn.clicked.connect(lambda: self._add_row("", "and"))
        layout.addWidget(add_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_formula()

    def _add_row(self, input_name: str, operator: str) -> None:
        row_widget = QWidget()
        row_h = QHBoxLayout(row_widget)
        row_h.setContentsMargins(0, 0, 0, 0)

        is_first = len(self._rows) == 0

        op_combo: QComboBox | None = None
        if not is_first:
            op_combo = QComboBox()
            op_combo.addItems(["and", "or", "xor"])
            op_combo.setCurrentText(operator)
            op_combo.setFixedWidth(60)
            op_combo.currentTextChanged.connect(self._update_formula)
            row_h.addWidget(op_combo)
        else:
            spacer = QLabel("      ")
            row_h.addWidget(spacer)

        inp_combo = QComboBox()
        inp_combo.addItems(self._available)
        if input_name in self._available:
            inp_combo.setCurrentText(input_name)
        inp_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        inp_combo.currentTextChanged.connect(self._update_formula)
        row_h.addWidget(inp_combo)

        remove_btn = QToolButton()
        remove_btn.setText("✕")
        remove_btn.clicked.connect(lambda: self._remove_row(row_widget))
        row_h.addWidget(remove_btn)

        self._entries_layout.addWidget(row_widget)
        self._rows.append((row_widget, op_combo, inp_combo))
        self._update_formula()

    def _remove_row(self, row_widget: QWidget) -> None:
        for i, (rw, _, _) in enumerate(self._rows):
            if rw is row_widget:
                self._rows.pop(i)
                rw.deleteLater()
                break
        # If first row was removed, clear the operator on the new first row
        if self._rows:
            new_first_widget, old_op, inp = self._rows[0]
            if old_op is not None:
                # Replace the operator combo with a spacer for the new first row
                layout = new_first_widget.layout()
                layout.removeWidget(old_op)
                old_op.deleteLater()
                spacer = QLabel("      ")
                layout.insertWidget(0, spacer)
                self._rows[0] = (new_first_widget, None, inp)
        self._update_formula()

    def _update_formula(self) -> None:
        if not self._rows:
            self._formula_label.setText("Formula: (empty)")
            return
        parts = [inp.currentText() for _, _, inp in self._rows]
        ops = [
            (op.currentText() if op else "")
            for _, op, _ in self._rows
        ]
        formula = parts[0] if parts else ""
        for i in range(1, len(parts)):
            formula = f"({formula} {ops[i]} {parts[i]})"
        self._formula_label.setText(f"Formula: {formula}")

    def get_config(self) -> CalculatedInput:
        entries = []
        for i, (_, op_combo, inp_combo) in enumerate(self._rows):
            op = op_combo.currentText() if op_combo else "and"
            entries.append(CalculatedEntry(
                input_name=inp_combo.currentText(),
                operator=op,
            ))
        return CalculatedInput(
            name=self._name_edit.text().strip(),
            enabled=self._enabled_check.isChecked(),
            entries=entries,
        )


# ---------------------------------------------------------------------------
# AS5311 dialog
# ---------------------------------------------------------------------------

class As5311Dialog(QDialog):
    """Dialog for creating/editing an As5311Input (restim magnetic linear encoder)."""

    def __init__(self, config: As5311Input | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AS5311 Sensor Input")
        self.setMinimumWidth(400)

        cfg = config or As5311Input(name="")
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit(cfg.name)
        form.addRow("Name:", self._name_edit)

        self._url_edit = QLineEdit(cfg.url)
        form.addRow("WebSocket URL:", self._url_edit)

        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(0.0, 999.0)
        self._threshold_spin.setDecimals(3)
        self._threshold_spin.setSuffix(" mm")
        self._threshold_spin.setSingleStep(0.1)
        self._threshold_spin.setValue(cfg.threshold_mm)
        self._threshold_spin.setToolTip("Position (mm) that maps to output value 0.")
        form.addRow("Threshold (→ 0):", self._threshold_spin)

        self._range_spin = QDoubleSpinBox()
        self._range_spin.setRange(0.01, 1000.0)
        self._range_spin.setDecimals(3)
        self._range_spin.setSuffix(" mm")
        self._range_spin.setSingleStep(0.5)
        self._range_spin.setValue(cfg.range_mm)
        self._range_spin.setToolTip(
            "Span (mm) from threshold to full scale.\n"
            "threshold + range maps to output value 100.\n"
            "AS5311 natural range is 2 mm per pole pair."
        )
        form.addRow("Range (→ 100):", self._range_spin)

        self._enabled_check = QCheckBox()
        self._enabled_check.setChecked(cfg.enabled)
        form.addRow("Enabled:", self._enabled_check)

        hint = QLabel(
            "<small>Connects to the restim AS5311 magnetic linear encoder WebSocket.<br>"
            "Message format: <tt>{\"x\": 0.000001}</tt> (position in metres).<br>"
            "Output = (position − threshold) ÷ range × 100, clamped to 0–100.<br>"
            "Inputs sharing the same URL share one WebSocket connection.</small>"
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)
        form.addRow("", hint)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_config(self) -> As5311Input:
        return As5311Input(
            name=self._name_edit.text().strip(),
            url=self._url_edit.text().strip(),
            enabled=self._enabled_check.isChecked(),
            threshold_mm=self._threshold_spin.value(),
            range_mm=self._range_spin.value(),
        )
