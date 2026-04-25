"""Add/Edit output configuration dialog."""

from __future__ import annotations

import re

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
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from funscript_gateway.models import (
    MqttOutputConfig,
    OutputConfig,
    TasmotaOutputConfig,
    ThresholdSwitchConfig,
    WsOutputConfig,
)

_FIELD_NAME_RE = re.compile(r'^[A-Za-z_$][A-Za-z0-9_$]*$')


class OutputDialog(QDialog):
    """Two-panel dialog for creating or editing an output configuration."""

    def __init__(self, inputs: list[str], config: OutputConfig | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Output Configuration")
        self.setMinimumWidth(560)

        self._inputs = inputs
        self._initial_config = config or OutputConfig()

        main = QVBoxLayout(self)
        outer = QHBoxLayout()

        # Left panel
        left = QWidget()
        left_layout = QFormLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)

        self._name_edit = QLineEdit(self._initial_config.name)
        left_layout.addRow("Name:", self._name_edit)

        self._input_combo = QComboBox()
        for a in inputs:
            self._input_combo.addItem(a)
        idx = self._input_combo.findText(self._initial_config.input_name)
        if idx >= 0:
            self._input_combo.setCurrentIndex(idx)
        left_layout.addRow("Input:", self._input_combo)

        self._enabled_check = QCheckBox()
        self._enabled_check.setChecked(self._initial_config.enabled)
        left_layout.addRow("Enabled:", self._enabled_check)

        self._on_pause_combo = QComboBox()
        for opt in ("hold", "force_off", "force_on"):
            self._on_pause_combo.addItem(opt)
        self._on_pause_combo.setCurrentText(self._initial_config.on_pause)
        left_layout.addRow("On pause:", self._on_pause_combo)

        self._on_disconnect_combo = QComboBox()
        for opt in ("force_off", "hold", "force_on"):
            self._on_disconnect_combo.addItem(opt)
        self._on_disconnect_combo.setCurrentText(self._initial_config.on_disconnect)
        left_layout.addRow("On disconnect:", self._on_disconnect_combo)

        self._on_missing_input_combo = QComboBox()
        for opt in ("force_off", "hold", "force_on"):
            self._on_missing_input_combo.addItem(opt)
        self._on_missing_input_combo.setCurrentText(self._initial_config.on_missing_input)
        left_layout.addRow("On missing input:", self._on_missing_input_combo)

        outer.addWidget(left)

        # Right panel — tabbed
        self._tabs = QTabWidget()
        self._threshold_tab_index = 0
        self._tabs.addTab(self._build_threshold_tab(), "Threshold")
        self._tabs.addTab(self._build_driver_tab(), "Driver")
        outer.addWidget(self._tabs)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        main.addLayout(outer)
        main.addWidget(buttons)

    def _on_accept(self) -> None:
        if self._driver_type_combo.currentText() == "ws_value":
            field = self._ws_field_name.text().strip()
            if not _FIELD_NAME_RE.match(field):
                QMessageBox.warning(
                    self,
                    "Invalid field name",
                    "Field name must be a valid identifier (letters, digits, _ or $, "
                    "not starting with a digit).",
                )
                return
        self.accept()

    def _build_threshold_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(8, 8, 8, 8)
        cfg = self._initial_config.threshold

        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(0.0, 100.0)
        self._threshold_spin.setDecimals(1)
        self._threshold_spin.setValue(cfg.threshold)
        form.addRow("Threshold (0-100):", self._threshold_spin)

        self._active_high_check = QCheckBox()
        self._active_high_check.setChecked(cfg.active_high)
        form.addRow("Active high:", self._active_high_check)

        self._hysteresis_spin = QDoubleSpinBox()
        self._hysteresis_spin.setRange(0.0, 100.0)
        self._hysteresis_spin.setDecimals(1)
        self._hysteresis_spin.setValue(cfg.hysteresis)
        form.addRow("Hysteresis:", self._hysteresis_spin)
        return w

    def _build_driver_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Driver type:"))
        self._driver_type_combo = QComboBox()
        self._driver_type_combo.addItems(["threshold_tasmota", "threshold_mqtt", "ws_value"])
        self._driver_type_combo.setCurrentText(self._initial_config.type)
        type_row.addWidget(self._driver_type_combo)
        type_row.addStretch()
        layout.addLayout(type_row)

        self._tasmota_group = self._build_tasmota_group()
        self._mqtt_group = self._build_mqtt_group()
        self._ws_group = self._build_ws_group()
        layout.addWidget(self._tasmota_group)
        layout.addWidget(self._mqtt_group)
        layout.addWidget(self._ws_group)
        layout.addStretch()

        self._driver_type_combo.currentTextChanged.connect(self._on_driver_type_changed)
        self._on_driver_type_changed(self._initial_config.type)
        return w

    _PULSE_MODE_HELP = (
        "Repeat Interval — Pulse Mode Keep-Alive\n\n"
        "If you want the Tasmota switch to automatically return to OFF even if "
        "the network disconnects or this app crashes, configure the device in "
        "pulse mode via the Tasmota console:\n\n"
        "    PulseTime1 160  →  switch turns off after 60 seconds\n"
        "    PulseTime1 130  →  switch turns off after 30 seconds\n\n"
        "(PulseTime values 112–65535 encode seconds as value − 100,\n"
        " so PulseTime 160 = 60 s, PulseTime 130 = 30 s.)\n\n"
        "When pulse mode is active, this app must repeatedly send the Power ON "
        "command to keep the relay closed while the output is active. Set the "
        "repeat interval to a value shorter than the pulse duration — for "
        "example, if you use PulseTime1 160 (60 s), set repeat interval to 45 s.\n\n"
        "Set to 0 to disable (command is only sent on state change)."
    )

    _WS_HELP = (
        "WebSocket Output — Continuous Value Stream\n\n"
        "Sends the input value (mapped to the configured output range) as JSON "
        "to the configured WebSocket endpoint at a fixed interval.\n\n"
        "Message format:\n"
        '    {"<field name>": <value>}\n\n'
        "The input value (0–100) is linearly mapped:\n"
        "    output = min_output + (max_output − min_output) × input ÷ 100\n\n"
        "So at input = 0 → output = min_output, at input = 100 → output = max_output.\n\n"
        "The connection is maintained persistently and reconnected automatically "
        "on failure (retry after 5 s).\n\n"
        "─────────────────────────────────────────\n"
        "Example — Heart Rate → restim pressure sensor:\n\n"
        "  URL:             ws://localhost:12346/sensors/pressure\n"
        "  Field name:      pressure\n"
        "  Send interval:   1.0 s\n"
        "  Min output:      100000\n"
        "  Max output:      110000\n\n"
        "This maps the input 0–100 range to restim's default pressure window "
        "(100000 = threshold, 110000 = threshold + range), so a heart rate input "
        "driving a restim pressure effect scales naturally with BPM."
    )

    def _build_tasmota_group(self) -> QGroupBox:
        group = QGroupBox("Tasmota")
        form = QFormLayout(group)
        cfg = self._initial_config.tasmota

        self._tasmota_host = QLineEdit(cfg.host)
        form.addRow("Host:", self._tasmota_host)

        self._tasmota_index = QSpinBox()
        self._tasmota_index.setRange(1, 8)
        self._tasmota_index.setValue(cfg.device_index)
        form.addRow("Device index:", self._tasmota_index)

        self._tasmota_timeout = QDoubleSpinBox()
        self._tasmota_timeout.setRange(0.5, 30.0)
        self._tasmota_timeout.setDecimals(1)
        self._tasmota_timeout.setValue(cfg.timeout_s)
        form.addRow("Timeout (s):", self._tasmota_timeout)

        self._tasmota_repeat = QSpinBox()
        self._tasmota_repeat.setRange(0, 3600)
        self._tasmota_repeat.setValue(cfg.repeat_interval_s)
        self._tasmota_repeat.setSpecialValueText("Off (0)")
        self._tasmota_repeat.setSuffix(" s")

        help_btn = QToolButton()
        help_btn.setText("?")
        help_btn.setToolTip("Click for help on pulse mode repeat interval")
        help_btn.clicked.connect(self._show_pulse_mode_help)

        repeat_row = QWidget()
        repeat_layout = QHBoxLayout(repeat_row)
        repeat_layout.setContentsMargins(0, 0, 0, 0)
        repeat_layout.addWidget(self._tasmota_repeat)
        repeat_layout.addWidget(help_btn)
        form.addRow("Repeat interval:", repeat_row)
        return group

    def _show_pulse_mode_help(self) -> None:
        QMessageBox.information(self, "Repeat Interval — Pulse Mode", self._PULSE_MODE_HELP)

    def _build_mqtt_group(self) -> QGroupBox:
        group = QGroupBox("MQTT")
        form = QFormLayout(group)
        cfg = self._initial_config.mqtt

        self._mqtt_broker_host = QLineEdit(cfg.broker_host)
        form.addRow("Broker host:", self._mqtt_broker_host)

        self._mqtt_broker_port = QSpinBox()
        self._mqtt_broker_port.setRange(1, 65535)
        self._mqtt_broker_port.setValue(cfg.broker_port)
        form.addRow("Broker port:", self._mqtt_broker_port)

        self._mqtt_username = QLineEdit(cfg.username)
        form.addRow("Username:", self._mqtt_username)

        self._mqtt_password = QLineEdit(cfg.password)
        self._mqtt_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self._mqtt_password)

        self._mqtt_command_topic = QLineEdit(cfg.command_topic)
        form.addRow("Command topic:", self._mqtt_command_topic)

        self._mqtt_payload_on = QLineEdit(cfg.payload_on)
        form.addRow("Payload ON:", self._mqtt_payload_on)

        self._mqtt_payload_off = QLineEdit(cfg.payload_off)
        form.addRow("Payload OFF:", self._mqtt_payload_off)

        self._mqtt_status_topic = QLineEdit(cfg.status_topic)
        form.addRow("Status topic:", self._mqtt_status_topic)

        self._mqtt_qos = QSpinBox()
        self._mqtt_qos.setRange(0, 2)
        self._mqtt_qos.setValue(cfg.qos)
        form.addRow("QoS:", self._mqtt_qos)

        self._mqtt_retain = QCheckBox()
        self._mqtt_retain.setChecked(cfg.retain)
        form.addRow("Retain:", self._mqtt_retain)
        return group

    def _build_ws_group(self) -> QGroupBox:
        group = QGroupBox("WebSocket")
        form = QFormLayout(group)
        cfg = self._initial_config.ws

        self._ws_url = QLineEdit(cfg.url)
        form.addRow("URL:", self._ws_url)

        field_row = QWidget()
        field_layout = QHBoxLayout(field_row)
        field_layout.setContentsMargins(0, 0, 0, 0)
        self._ws_field_name = QLineEdit(cfg.field_name)
        ws_help_btn = QToolButton()
        ws_help_btn.setText("?")
        ws_help_btn.setToolTip("Click for help on WebSocket output")
        ws_help_btn.clicked.connect(self._show_ws_help)
        field_layout.addWidget(self._ws_field_name)
        field_layout.addWidget(ws_help_btn)
        form.addRow("Field name:", field_row)

        self._ws_interval = QDoubleSpinBox()
        self._ws_interval.setRange(0.1, 10.0)
        self._ws_interval.setDecimals(1)
        self._ws_interval.setSingleStep(0.1)
        self._ws_interval.setSuffix(" s")
        self._ws_interval.setValue(cfg.send_interval_s)
        form.addRow("Send interval:", self._ws_interval)

        self._ws_min_output = QDoubleSpinBox()
        self._ws_min_output.setRange(-1e9, 1e9)
        self._ws_min_output.setDecimals(2)
        self._ws_min_output.setValue(cfg.min_output)
        form.addRow("Min output:", self._ws_min_output)

        self._ws_max_output = QDoubleSpinBox()
        self._ws_max_output.setRange(-1e9, 1e9)
        self._ws_max_output.setDecimals(2)
        self._ws_max_output.setValue(cfg.max_output)
        form.addRow("Max output:", self._ws_max_output)

        return group

    def _show_ws_help(self) -> None:
        QMessageBox.information(self, "WebSocket Output", self._WS_HELP)

    def _on_driver_type_changed(self, driver_type: str) -> None:
        is_tasmota = driver_type == "threshold_tasmota"
        is_mqtt = driver_type == "threshold_mqtt"
        is_ws = driver_type == "ws_value"
        self._tasmota_group.setVisible(is_tasmota)
        self._mqtt_group.setVisible(is_mqtt)
        self._ws_group.setVisible(is_ws)
        # Threshold tab is irrelevant for WebSocket outputs — disable it so the
        # Driver tab stays selected without any current-index/visibility quirks
        self._tabs.setTabEnabled(self._threshold_tab_index, not is_ws)
        if is_ws:
            self._tabs.setCurrentIndex(1)

    def get_config(self) -> OutputConfig:
        """Return the OutputConfig as configured in the dialog."""
        threshold = ThresholdSwitchConfig(
            threshold=self._threshold_spin.value(),
            active_high=self._active_high_check.isChecked(),
            hysteresis=self._hysteresis_spin.value(),
        )
        tasmota = TasmotaOutputConfig(
            host=self._tasmota_host.text().strip(),
            device_index=self._tasmota_index.value(),
            timeout_s=self._tasmota_timeout.value(),
            repeat_interval_s=self._tasmota_repeat.value(),
        )
        mqtt = MqttOutputConfig(
            broker_host=self._mqtt_broker_host.text().strip(),
            broker_port=self._mqtt_broker_port.value(),
            username=self._mqtt_username.text().strip(),
            password=self._mqtt_password.text(),
            command_topic=self._mqtt_command_topic.text().strip(),
            payload_on=self._mqtt_payload_on.text(),
            payload_off=self._mqtt_payload_off.text(),
            status_topic=self._mqtt_status_topic.text().strip(),
            qos=self._mqtt_qos.value(),
            retain=self._mqtt_retain.isChecked(),
        )
        ws = WsOutputConfig(
            url=self._ws_url.text().strip(),
            field_name=self._ws_field_name.text().strip(),
            send_interval_s=self._ws_interval.value(),
            min_output=self._ws_min_output.value(),
            max_output=self._ws_max_output.value(),
        )
        return OutputConfig(
            name=self._name_edit.text().strip(),
            enabled=self._enabled_check.isChecked(),
            type=self._driver_type_combo.currentText(),
            input_name=self._input_combo.currentText(),
            on_pause=self._on_pause_combo.currentText(),
            on_disconnect=self._on_disconnect_combo.currentText(),
            on_missing_input=self._on_missing_input_combo.currentText(),
            threshold=threshold,
            tasmota=tasmota,
            mqtt=mqtt,
            ws=ws,
        )
