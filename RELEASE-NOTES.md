# funscript-gateway — Release Notes

---

## v0.1.8

### What is funscript-gateway?

A Windows desktop bridge service that connects video players to smart home and IoT outputs using funscript haptic axis data.

**Supported players:** HereSphere (VR), MPC-HC  
**Supported outputs:** Tasmota (HTTP), MQTT, WebSocket continuous value

When you play a video, the gateway reads the associated `.funscript` file, evaluates values in real time, and drives physical outputs — smart plugs, MQTT devices, or any WebSocket endpoint — based on configurable thresholds and mappings.

---

### Input types

Seven input types are supported. Each produces a 0–100 value that any number of outputs can read from:

- **Funscript Axis** — reads interpolated haptic values from a `.funscript` file at the current playback position
- **Restim** — polls restim's HTTP status endpoint and evaluates playing state / volume conditions
- **AS5311 Magnetic Encoder** — receives position data from the restim AS5311 encoder via WebSocket, maps a configurable window to 0–100
- **Tasmota** — polls a Tasmota device's power state (OFF→0, ON→100)
- **Calculated (Logical)** — combines inputs with AND / OR / XOR boolean logic
- **Calculated (Arithmetic)** — weighted average of multiple inputs
- **Heart Rate (BLE)** — connects to a BLE chest strap or compatible heart rate sensor via the standard GATT Heart Rate Profile, maps BPM to 0–100

### Output types

- **Threshold → Tasmota (HTTP)** — switches a Tasmota relay on/off based on a configurable threshold and hysteresis; optional pulse-mode keep-alive repeat
- **Threshold → MQTT** — publishes ON/OFF payloads to any MQTT broker (Home Assistant, Mosquitto, Tasmota MQTT, etc.)
- **Value → WebSocket** — sends a continuous numeric value to a WebSocket endpoint at a configurable interval; input 0–100 is linearly mapped to a configurable output range

### Automation

- **Restim autostart** — when playback begins, automatically starts any restim instances that are currently stopped

---

### What's new since v0.1.5

#### Heart Rate (BLE) input
Direct BLE connection to any chest strap or compatible heart rate sensor implementing the Bluetooth SIG Heart Rate Profile (Polar H10, Wahoo TICKR, Garmin HRM, Coospo, and others). No third-party app or API required. BPM is mapped linearly to 0–100 using configurable min/max BPM bounds. The Inputs tab shows the live BPM reading. A **Scan…** button in the input dialog discovers nearby paired HR devices automatically. Retries on disconnect every 5 seconds.

**Prerequisite:** the device must be paired in Windows Bluetooth settings first.

#### WebSocket continuous-value output
A new output type (`Value → WebSocket`) that streams the input value as JSON to any WebSocket endpoint at a configurable interval (0.1–10 s). The input 0–100 range is linearly mapped to a configurable min/max output range:

```
output = min_output + (max_output − min_output) × input ÷ 100
```

The connection is maintained persistently and reconnected automatically on failure.

**Primary use case — Heart Rate → restim pressure:** configure the output with URL `ws://localhost:12346/sensors/pressure`, field name `pressure`, min output `100000`, max output `110000`. This drives restim's pressure effect in proportion to heart rate, using restim's default pressure threshold and range, with no additional middleware.

#### Bug fixes
- Fixed WebSocket output dialog showing the wrong tab content when editing an existing ws_value output (the Threshold tab was being hidden but its content was still rendered; now disabled cleanly and the Driver tab is selected automatically)

---

## v0.1.5

### What's new

#### Restim autostart
When playback begins, funscript-gateway can automatically start any restim instances that are currently stopped. Configure in **Settings → Player Settings**: tick **On start playing, start restim instances** and enter the comma-separated restim base URLs (e.g. `http://localhost:12348/v1`).

On every play-start transition the gateway checks `GET {url}/status` for each URL. If `playing` is `false` it calls `GET {url}/actions/start`. Instances already playing are left undisturbed. Failures are logged as warnings and do not affect playback.

---

## v0.1.4

### What's new

#### Inputs system (replaces Axes tab)
The Axes tab has been replaced by a full Inputs tab supporting multiple input types beyond funscript files:

- **Restim** — polls restim's HTTP status endpoint; evaluates playing state and volume conditions
- **AS5311 Magnetic Encoder** — WebSocket connection to restim's linear encoder; maps position window to 0–100
- **Tasmota** — polls a Tasmota device's power state
- **Calculated (Logical)** — combines inputs with AND / OR / XOR logic
- **Calculated (Arithmetic)** — weighted average of multiple inputs

#### MQTT output
New output driver that publishes ON/OFF payloads to an MQTT broker. Compatible with Home Assistant, Mosquitto, Tasmota MQTT, and any standard broker.

#### Tasmota pulse mode keep-alive
Tasmota outputs support a configurable repeat interval. When set, the ON command is re-sent periodically while the output is active — required when the device is configured with `PulseTime` for hardware safety auto-off.

---

## v0.1.1

### What's new

- Initial public release
- HereSphere and MPC-HC player support
- Funscript axis input with linear interpolation
- Tasmota HTTP output with threshold + hysteresis switching
- System tray, Settings, Status, Inputs, and Outputs tabs
- Rotating log file at `%APPDATA%\funscript-gateway\logs\`
