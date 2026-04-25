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

import asyncio

from funscript_gateway.models import (
    ArithmeticEntry,
    ArithmeticInput,
    As5311Input,
    CalculatedEntry,
    CalculatedInput,
    FunscriptAxisInput,
    HeartRateInput,
    RestimCondition,
    RestimInput,
    TasmotaInput,
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
    """Dialog for creating/editing a CalculatedInput (Logical).

    Each entry converts an input value to a boolean using a configurable
    threshold and direction (≥ / <), then combines them with AND/OR/XOR.
    """

    def __init__(
        self,
        available_inputs: list[str],
        config: CalculatedInput | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Calculated Input (Logical)")
        self.setMinimumWidth(540)

        cfg = config or CalculatedInput(name="")
        self._available = list(available_inputs)

        layout = QVBoxLayout(self)

        top_form = QFormLayout()
        self._name_edit = QLineEdit(cfg.name)
        top_form.addRow("Name:", self._name_edit)

        self._enabled_check = QCheckBox()
        self._enabled_check.setChecked(cfg.enabled)
        top_form.addRow("Enabled:", self._enabled_check)
        layout.addLayout(top_form)

        self._formula_label = QLabel()
        self._formula_label.setWordWrap(True)
        self._formula_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._formula_label)

        self._entries_widget = QWidget()
        self._entries_layout = QVBoxLayout(self._entries_widget)
        self._entries_layout.setContentsMargins(0, 0, 0, 0)
        self._entries_layout.setSpacing(4)
        layout.addWidget(self._entries_widget)

        # Rows: list of (row_widget, op_combo|None, inp_combo, dir_combo, thresh_spin)
        self._rows: list[tuple] = []

        for entry in cfg.entries:
            self._add_row(entry.input_name, entry.operator, entry.above, entry.threshold)
        if not self._rows:
            self._add_row("", "and", True, 50.0)

        add_btn = QPushButton("Add Entry")
        add_btn.clicked.connect(lambda: self._add_row("", "and", True, 50.0))
        layout.addWidget(add_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_formula()

    def _add_row(self, input_name: str, operator: str, above: bool, threshold: float) -> None:
        row_widget = QWidget()
        row_h = QHBoxLayout(row_widget)
        row_h.setContentsMargins(0, 0, 0, 0)
        row_h.setSpacing(4)

        is_first = len(self._rows) == 0

        op_combo: QComboBox | None = None
        if not is_first:
            op_combo = QComboBox()
            op_combo.addItems(["and", "or", "xor"])
            op_combo.setCurrentText(operator)
            op_combo.setFixedWidth(112)
            op_combo.currentTextChanged.connect(self._update_formula)
            row_h.addWidget(op_combo)
        else:
            spacer = QLabel("      ")
            spacer.setFixedWidth(112)
            row_h.addWidget(spacer)

        inp_combo = QComboBox()
        inp_combo.addItems(self._available)
        if input_name in self._available:
            inp_combo.setCurrentText(input_name)
        inp_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        inp_combo.currentTextChanged.connect(self._update_formula)
        row_h.addWidget(inp_combo)

        dir_combo = QComboBox()
        dir_combo.addItems(["\u2265", "<"])   # ≥ / <
        dir_combo.setCurrentIndex(0 if above else 1)
        dir_combo.setFixedWidth(88)
        dir_combo.currentTextChanged.connect(self._update_formula)
        row_h.addWidget(dir_combo)

        thresh_spin = QDoubleSpinBox()
        thresh_spin.setRange(0.0, 100.0)
        thresh_spin.setDecimals(1)
        thresh_spin.setSingleStep(5.0)
        thresh_spin.setValue(threshold)
        thresh_spin.setFixedWidth(144)
        thresh_spin.valueChanged.connect(self._update_formula)
        row_h.addWidget(thresh_spin)

        remove_btn = QToolButton()
        remove_btn.setText("\u2715")
        remove_btn.clicked.connect(lambda: self._remove_row(row_widget))
        row_h.addWidget(remove_btn)

        self._entries_layout.addWidget(row_widget)
        self._rows.append((row_widget, op_combo, inp_combo, dir_combo, thresh_spin))
        self._update_formula()

    def _remove_row(self, row_widget: QWidget) -> None:
        for i, (rw, *_) in enumerate(self._rows):
            if rw is row_widget:
                self._rows.pop(i)
                rw.deleteLater()
                break
        # If first row was removed, replace its operator combo with a spacer
        if self._rows:
            new_first_widget, old_op, inp, dir_combo, thresh_spin = self._rows[0]
            if old_op is not None:
                lyt = new_first_widget.layout()
                lyt.removeWidget(old_op)
                old_op.deleteLater()
                spacer = QLabel("      ")
                spacer.setFixedWidth(56)
                lyt.insertWidget(0, spacer)
                self._rows[0] = (new_first_widget, None, inp, dir_combo, thresh_spin)
        self._update_formula()

    def _update_formula(self) -> None:
        if not self._rows:
            self._formula_label.setText("Formula: (empty)")
            return
        parts = [
            f"{inp.currentText()} {d.currentText()} {t.value():.1f}"
            for _, _, inp, d, t in self._rows
        ]
        ops = [op.currentText() if op else "" for _, op, *_ in self._rows]
        formula = parts[0]
        for i in range(1, len(parts)):
            formula = f"({formula} {ops[i]} {parts[i]})"
        self._formula_label.setText(f"Formula: {formula}")

    def get_config(self) -> CalculatedInput:
        entries = [
            CalculatedEntry(
                input_name=inp_combo.currentText(),
                operator=op_combo.currentText() if op_combo else "and",
                above=(dir_combo.currentText() == "\u2265"),
                threshold=thresh_spin.value(),
            )
            for _, op_combo, inp_combo, dir_combo, thresh_spin in self._rows
        ]
        return CalculatedInput(
            name=self._name_edit.text().strip(),
            enabled=self._enabled_check.isChecked(),
            entries=entries,
        )


# ---------------------------------------------------------------------------
# Arithmetic dialog
# ---------------------------------------------------------------------------

class ArithmeticDialog(QDialog):
    """Dialog for creating/editing an ArithmeticInput (weighted average)."""

    def __init__(
        self,
        available_inputs: list[str],
        config: ArithmeticInput | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Calculated Input (Arithmetic)")
        self.setMinimumWidth(480)

        cfg = config or ArithmeticInput(name="")
        self._available = list(available_inputs)

        layout = QVBoxLayout(self)

        top_form = QFormLayout()
        self._name_edit = QLineEdit(cfg.name)
        top_form.addRow("Name:", self._name_edit)
        self._enabled_check = QCheckBox()
        self._enabled_check.setChecked(cfg.enabled)
        top_form.addRow("Enabled:", self._enabled_check)
        layout.addLayout(top_form)

        self._formula_label = QLabel()
        self._formula_label.setWordWrap(True)
        self._formula_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._formula_label)

        self._entries_widget = QWidget()
        self._entries_layout = QVBoxLayout(self._entries_widget)
        self._entries_layout.setContentsMargins(0, 0, 0, 0)
        self._entries_layout.setSpacing(4)
        layout.addWidget(self._entries_widget)

        # _rows: list of (row_widget, inp_combo, mult_combo)
        self._rows: list[tuple] = []

        for entry in cfg.entries:
            self._add_row(entry.input_name, entry.multiplier)
        if not self._rows:
            self._add_row("", 1)

        add_btn = QPushButton("Add Entry")
        add_btn.clicked.connect(lambda: self._add_row("", 1))
        layout.addWidget(add_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_formula()

    def _add_row(self, input_name: str, multiplier: int) -> None:
        row_widget = QWidget()
        h = QHBoxLayout(row_widget)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)

        inp_combo = QComboBox()
        inp_combo.addItems(self._available)
        if input_name in self._available:
            inp_combo.setCurrentText(input_name)
        inp_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        inp_combo.currentTextChanged.connect(self._update_formula)
        h.addWidget(inp_combo)

        times_label = QLabel("\u00d7")   # ×
        h.addWidget(times_label)

        mult_combo = QComboBox()
        mult_combo.addItems(["1", "2", "3", "4"])
        mult_combo.setCurrentText(str(multiplier))
        mult_combo.setFixedWidth(60)
        mult_combo.currentTextChanged.connect(self._update_formula)
        h.addWidget(mult_combo)

        remove_btn = QToolButton()
        remove_btn.setText("\u2715")
        remove_btn.clicked.connect(lambda: self._remove_row(row_widget))
        h.addWidget(remove_btn)

        self._entries_layout.addWidget(row_widget)
        self._rows.append((row_widget, inp_combo, mult_combo))
        self._update_formula()

    def _remove_row(self, row_widget: QWidget) -> None:
        for i, (rw, *_) in enumerate(self._rows):
            if rw is row_widget:
                self._rows.pop(i)
                rw.deleteLater()
                break
        self._update_formula()

    def _update_formula(self) -> None:
        if not self._rows:
            self._formula_label.setText("Formula: (empty)")
            return
        parts = []
        total_weight = 0
        for _, inp, mult in self._rows:
            m = int(mult.currentText())
            total_weight += m
            name = inp.currentText() or "?"
            parts.append(f"{name} \u00d7 {m}" if m > 1 else name)
        inner = " + ".join(parts)
        if len(self._rows) > 1:
            inner = f"({inner})"
        self._formula_label.setText(f"Formula: {inner} \u00f7 {total_weight}")

    def get_config(self) -> ArithmeticInput:
        entries = [
            ArithmeticEntry(
                input_name=inp_combo.currentText(),
                multiplier=int(mult_combo.currentText()),
            )
            for _, inp_combo, mult_combo in self._rows
        ]
        return ArithmeticInput(
            name=self._name_edit.text().strip(),
            enabled=self._enabled_check.isChecked(),
            entries=entries,
        )


# ---------------------------------------------------------------------------
# Tasmota input dialog
# ---------------------------------------------------------------------------

class TasmotaInputDialog(QDialog):
    """Dialog for creating/editing a TasmotaInput (polls device power state)."""

    def __init__(self, config: TasmotaInput | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tasmota Input")
        self.setMinimumWidth(360)

        cfg = config or TasmotaInput(name="")
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit(cfg.name)
        form.addRow("Name:", self._name_edit)

        self._host_edit = QLineEdit(cfg.host)
        self._host_edit.setPlaceholderText("e.g. 192.168.1.42 or tasmota-abc123")
        form.addRow("Host:", self._host_edit)

        self._index_spin = QDoubleSpinBox()
        self._index_spin.setRange(1, 8)
        self._index_spin.setDecimals(0)
        self._index_spin.setValue(cfg.device_index)
        form.addRow("Device index:", self._index_spin)

        self._poll_spin = QDoubleSpinBox()
        self._poll_spin.setRange(0.5, 60.0)
        self._poll_spin.setDecimals(1)
        self._poll_spin.setSuffix(" s")
        self._poll_spin.setValue(cfg.poll_interval_s)
        form.addRow("Poll interval:", self._poll_spin)

        self._timeout_spin = QDoubleSpinBox()
        self._timeout_spin.setRange(0.5, 30.0)
        self._timeout_spin.setDecimals(1)
        self._timeout_spin.setSuffix(" s")
        self._timeout_spin.setValue(cfg.timeout_s)
        form.addRow("Timeout:", self._timeout_spin)

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

    def get_config(self) -> TasmotaInput:
        return TasmotaInput(
            name=self._name_edit.text().strip(),
            host=self._host_edit.text().strip(),
            device_index=int(self._index_spin.value()),
            poll_interval_s=self._poll_spin.value(),
            timeout_s=self._timeout_spin.value(),
            enabled=self._enabled_check.isChecked(),
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


# ---------------------------------------------------------------------------
# HeartRate dialog
# ---------------------------------------------------------------------------

class HeartRateInputDialog(QDialog):
    """Dialog for creating/editing a HeartRateInput (BLE Heart Rate Profile)."""

    def __init__(self, config: HeartRateInput | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Heart Rate Input (BLE)")
        self.setMinimumWidth(420)

        cfg = config or HeartRateInput(name="")
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit(cfg.name)
        form.addRow("Name:", self._name_edit)

        # Device address row: editable field + scan button
        addr_row = QHBoxLayout()
        self._addr_edit = QLineEdit(cfg.device_address)
        self._addr_edit.setPlaceholderText("BLE address — use Scan to discover")
        addr_row.addWidget(self._addr_edit)
        self._scan_btn = QPushButton("Scan…")
        self._scan_btn.setFixedWidth(70)
        self._scan_btn.clicked.connect(self._on_scan)
        addr_row.addWidget(self._scan_btn)
        form.addRow("Device address:", addr_row)

        # Scan results combo (hidden until first scan)
        self._results_combo = QComboBox()
        self._results_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._results_combo.currentIndexChanged.connect(self._on_result_selected)
        self._results_combo.hide()
        form.addRow("Found devices:", self._results_combo)
        self._results_label = QLabel()
        self._results_label.hide()
        form.addRow("", self._results_label)

        self._label_edit = QLineEdit(cfg.device_label)
        self._label_edit.setPlaceholderText("Auto-filled by scan, or leave blank")
        form.addRow("Device name:", self._label_edit)

        hint = QLabel(
            "<small>Device must be <b>paired</b> in Windows Bluetooth settings first.<br>"
            "Supports BLE chest straps and watches in HR Broadcast mode.</small>"
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        form.addRow("", hint)

        self._min_spin = QDoubleSpinBox()
        self._min_spin.setRange(20, 250)
        self._min_spin.setDecimals(0)
        self._min_spin.setSuffix(" BPM")
        self._min_spin.setValue(cfg.scale_min_bpm)
        self._min_spin.setToolTip("BPM value that maps to output 0")
        form.addRow("Min BPM (→ 0):", self._min_spin)

        self._max_spin = QDoubleSpinBox()
        self._max_spin.setRange(20, 250)
        self._max_spin.setDecimals(0)
        self._max_spin.setSuffix(" BPM")
        self._max_spin.setValue(cfg.scale_max_bpm)
        self._max_spin.setToolTip("BPM value that maps to output 100")
        form.addRow("Max BPM (→ 100):", self._max_spin)

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

    def _on_scan(self) -> None:
        self._scan_btn.setEnabled(False)
        self._scan_btn.setText("…")
        self._results_combo.clear()
        self._results_combo.show()
        self._results_label.hide()
        asyncio.ensure_future(self._do_scan())

    async def _do_scan(self) -> None:
        _HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
        try:
            from bleak import BleakScanner
            devices = await BleakScanner.discover(timeout=5.0, service_uuids=[_HR_SERVICE_UUID])
            if not self.isVisible():
                return
            self._results_combo.clear()
            if devices:
                self._results_combo.addItem("— select a device —", ("", ""))
                for d in sorted(devices, key=lambda x: x.name or ""):
                    label = f"{d.name or 'Unknown'} [{d.address}]"
                    self._results_combo.addItem(label, (d.address, d.name or ""))
            else:
                self._results_combo.addItem("No HR devices found (is device paired?)", ("", ""))
        except ImportError:
            if not self.isVisible():
                return
            self._results_combo.clear()
            self._results_combo.addItem("bleak not installed — run: pip install bleak", ("", ""))
        except Exception as exc:  # noqa: BLE001
            if not self.isVisible():
                return
            self._results_combo.clear()
            self._results_combo.addItem(f"Scan error: {exc}", ("", ""))
        finally:
            if self.isVisible():
                self._scan_btn.setEnabled(True)
                self._scan_btn.setText("Scan…")

    def _on_result_selected(self, index: int) -> None:
        if index < 0:
            return
        data = self._results_combo.itemData(index)
        if not data:
            return
        address, name = data
        if address:
            self._addr_edit.setText(address)
            if name and not self._label_edit.text():
                self._label_edit.setText(name)

    def get_config(self) -> HeartRateInput:
        return HeartRateInput(
            name=self._name_edit.text().strip(),
            device_address=self._addr_edit.text().strip(),
            device_label=self._label_edit.text().strip(),
            enabled=self._enabled_check.isChecked(),
            scale_min_bpm=int(self._min_spin.value()),
            scale_max_bpm=int(self._max_spin.value()),
        )
