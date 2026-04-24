# funscript-gateway

A Windows desktop bridge service that connects video players to smart home and IoT outputs using funscript haptic axis data.

## What it does

When you play a video in a supported player, funscript-gateway reads the associated `.funscript` file, evaluates the haptic values in real time, and drives physical outputs (smart plugs, MQTT devices) based on configurable thresholds. Useful for synchronising real-world effects — lighting, devices, anything switchable — to video content.

**Supported players:**
- [HereSphere](https://heresphere.com/) (VR player) — event-driven TCP connection
- [MPC-HC](https://github.com/clsid2/mpc-hc) — HTTP polling via web interface

**Supported outputs:**
- Tasmota smart plugs — HTTP API
- Any MQTT broker / device (e.g. Home Assistant, Tasmota via MQTT)

---

## How it works

```
Video player ──► funscript-gateway ──► evaluates input value at current timestamp
                                    │   (funscript axis / restim poll / encoder / calculated)
                                    └──► applies threshold + hysteresis ──► ON / OFF
                                                                         └──► Tasmota HTTP
                                                                         └──► MQTT publish
```

1. The player reports its current playback position.
2. For **Funscript Axis** inputs: the gateway looks up the funscript file (e.g. `myvideo.volume.funscript`) and interpolates its value (0–100) at the current timestamp.
3. For **Restim** inputs: the gateway polls the configured HTTP endpoint at the configured interval and evaluates conditions (playing state, volume thresholds).
4. For **AS5311** inputs: the gateway receives position data from a magnetic linear encoder via WebSocket and maps it to 0–100 using configurable threshold and range.
5. For **Tasmota** inputs: the gateway polls a Tasmota device's power state via HTTP and maps OFF→0, ON→100.
6. For **Calculated (Logical)** inputs: the gateway combines one or more inputs using AND / OR / XOR logic, converting each input to a boolean with its own configurable threshold and direction.
7. For **Calculated (Arithmetic)** inputs: the gateway computes a weighted average of selected inputs — each entry has a configurable multiplier (1–4) — and outputs the result as a continuous 0–100 value.
8. Every 50 ms, each output reads its assigned input value and applies a threshold + hysteresis to produce ON or OFF, which is sent to the device.

### Funscript file naming

Files must follow the pattern:

```
{video-basename}.{axis-name}.funscript
```

For example, if the video is `scene.mp4` and you have an axis named `volume`:

```
scene.volume.funscript
```

The gateway searches configured search paths and the video's own folder.

---

## Installation

Download the latest `funscript-gateway.exe` from [Releases](../../releases) and run it. No installation required.

To run from source:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m funscript_gateway.main
```

---

## Player setup

### HereSphere

Enable the companion app / network API in HereSphere settings. The default port is `23554`.

In funscript-gateway → **Settings** tab:
- Player type: `heresphere`
- Host: `127.0.0.1` (or the HereSphere machine's IP)
- Port: `23554`

### MPC-HC

Enable the Web Interface in MPC-HC: **View → Options → Player → Web Interface**, tick *Listen on port* and set port `13579`.

In funscript-gateway → **Settings** tab:
- Player type: `mpc_hc`
- Host: `127.0.0.1`
- Port: `13579`
- Poll interval: `150` ms

---

## Automation

### Restim autostart

When you start playing a video, funscript-gateway can automatically start any restim instances that are currently stopped.

In funscript-gateway → **Settings** tab → **Player Settings**:
- Tick **On start playing, start restim instances**
- Enter the comma-separated restim base URLs in the **Restim URLs** field (e.g. `http://localhost:12348/v1,http://localhost:12349/v1`)

On every play-start transition (player goes from not-playing to playing), the gateway checks `GET {url}/status` for each configured URL. If `playing` is `false`, it calls `GET {url}/actions/start`. Instances already playing are left undisturbed. Failures are logged as warnings and do not affect playback.

---

## Inputs

In the **Inputs** tab, configure the data sources that outputs read from. Six input types are available:

### Funscript Axis

Reads the interpolated value from a `.funscript` file at the current playback position.

| Setting | Description |
|---------|-------------|
| **Name** | Axis name — must match the funscript filename segment (e.g. `volume` for `myvideo.volume.funscript`) |
| **Default value** | Value (0–1) to use when the funscript file is not found for the current video. Outputs always receive this value when the file is absent; `on_missing_input` does not apply. |
| **Enabled** | Toggle without deleting |

The **Refresh** button re-runs file discovery for the current video.

### Restim

Polls an HTTP endpoint and evaluates one or more conditions against the response. Produces ON (100) when all enabled conditions pass, OFF (0) otherwise. Evaluated continuously regardless of player state.

| Setting | Description |
|---------|-------------|
| **Name** | Input name |
| **URL** | HTTP GET endpoint (default: `http://localhost:12348/v1/status`) |
| **Poll interval** | How often to poll, in seconds |
| **Default state** | Output when the endpoint is unreachable: `off` or `on` |
| **Conditions** | Playing (yes/no/any), volume UI above/below threshold, volume device above/below threshold. Each condition has its own enable checkbox. All enabled conditions must pass. |

### AS5311 Magnetic Encoder

Receives position data from the restim AS5311 magnetic linear encoder via a persistent WebSocket connection. Maps a configurable position window to 0–100. Evaluated continuously regardless of player state.

| Setting | Description |
|---------|-------------|
| **Name** | Input name |
| **WebSocket URL** | Encoder endpoint (default: `ws://localhost:12346/sensors/as5311`) |
| **Threshold (mm)** | Position that maps to output value 0 |
| **Range (mm)** | Span from threshold to full scale. `threshold + range` maps to output value 100. The natural AS5311 range is 2 mm per pole pair. |

Multiple inputs pointing to the same URL share one WebSocket connection.

### Tasmota

Polls a Tasmota device's power state via its HTTP API. Maps OFF→0 (0%), ON→100 (100%). Evaluated continuously regardless of player state.

| Setting | Description |
|---------|-------------|
| **Name** | Input name |
| **Host** | Hostname or IP of the Tasmota device |
| **Device index** | Power channel index, usually `1` |
| **Poll interval** | How often to query, in seconds |
| **Timeout** | HTTP request timeout, in seconds |

### Calculated (Logical)

Combines one or more non-calculated inputs using AND / OR / XOR, evaluated left-to-right. Each entry first converts its input's continuous 0–100 value to a boolean using a configurable threshold and direction, then combines the results. Produces ON (100) or OFF (0). Evaluated continuously regardless of player state.

| Setting | Description |
|---------|-------------|
| **Name** | Input name |
| **Entries** | At least 1 non-calculated input. First entry has no operator; subsequent entries specify AND / OR / XOR. Each entry also has a direction (≥ / <) and threshold (0–100) for the boolean conversion. |

The formula is shown live in the dialog, e.g. `(vibration ≥ 60.0 or restim < 30.0)`.

### Calculated (Arithmetic)

Computes a weighted average of selected inputs. Each entry contributes its current value multiplied by a configurable weight (1–4); the result is divided by the total weight and clamped to 0–100. Useful for blending multiple continuous inputs into a single value. Arithmetic inputs can reference both primary inputs and Calculated (Logical) inputs. Evaluated continuously regardless of player state.

| Setting | Description |
|---------|-------------|
| **Name** | Input name |
| **Entries** | At least 1 input. Each entry has an input selection and a multiplier (1–4). |

Formula: `output = Σ(value_i × mult_i) / Σ(mult_i)`, clamped to 0–100. The live formula label shows e.g. `(A × 2 + B) ÷ 3`.

---

## Outputs

Each output maps one input to one device. Add outputs in the **Outputs** tab.

### Common settings

| Setting | Description |
|---------|-------------|
| **Name** | Display name |
| **Input** | Which input value to read |
| **Enabled** | Toggle without deleting |
| **On pause** | What to do when playback is paused (only relevant for Funscript Axis inputs): `hold` (keep last state), `force_off`, `force_on` |
| **On disconnect** | What to do when the player disconnects: `hold`, `force_off`, `force_on` |
| **On missing input** | What to do when the named input is not in the inputs list: `hold`, `force_off`, `force_on` |

### Threshold settings

| Setting | Description |
|---------|-------------|
| **Threshold** | 0–100 value at which the output switches |
| **Active high** | If checked: ON when value ≥ threshold. If unchecked: ON when value < threshold |
| **Hysteresis** | Dead-band around threshold to prevent rapid toggling. E.g. threshold=50, hysteresis=10 → turns ON at 60, turns OFF at 40 |

---

## Driver types

### Tasmota (HTTP)

Sends commands directly to Tasmota's HTTP API. No broker required.

| Setting | Description |
|---------|-------------|
| **Host** | Hostname or IP of the Tasmota device (e.g. `tasmota-[device-id]` or `192.168.1.[x]`) |
| **Device index** | Power channel index, usually `1` |
| **Timeout (s)** | HTTP request timeout |
| **Repeat interval (s)** | When > 0, re-sends the ON command every N seconds while the output is active. Required when the device is in pulse mode (see below). `0` = disabled. |

#### Pulse mode (automatic hardware safety off)

If you want the device to turn itself off automatically even if your network or this app fails, configure Tasmota's *PulseTime* in the Tasmota console:

```
PulseTime1 160   # channel 1 auto-off after 60 seconds
PulseTime1 130   # channel 1 auto-off after 30 seconds
```

*(PulseTime values 112–65535 encode seconds as `value − 100`.)*

When pulse mode is active, funscript-gateway must repeatedly send the ON command to keep the relay closed. Set **Repeat interval** to a value shorter than the pulse duration — e.g. if you use `PulseTime1 160` (60 s), set repeat interval to `45`.

Example output config for a Tasmota plug on the local network:

```toml
[[outputs]]
name = "my-plug"
enabled = true
type = "threshold_tasmota"
input_name = "volume"
on_pause = "hold"
on_disconnect = "force_off"
on_missing_input = "force_off"

[outputs.threshold]
threshold = 50.0
active_high = true
hysteresis = 10.0

[outputs.tasmota]
host = "tasmota-[device-hostname]"
device_index = 1
timeout_s = 3.0
repeat_interval_s = 0   # set to e.g. 45 if using PulseTime1 160
```

### MQTT

Publishes ON/OFF payloads to an MQTT broker. Works with Home Assistant, Mosquitto, or any Tasmota device connected via MQTT.

| Setting | Description |
|---------|-------------|
| **Broker host** | Hostname or IP of the MQTT broker |
| **Broker port** | Usually `1883` |
| **Username / Password** | Broker credentials if required |
| **Command topic** | Topic to publish to (e.g. `cmnd/[device-id]/POWER`) |
| **Payload ON / OFF** | Message sent for each state (Tasmota default: `ON` / `OFF`) |
| **Status topic** | Optional topic to subscribe to for confirmed state feedback (e.g. `stat/[device-id]/POWER`) |
| **QoS** | MQTT quality of service: `0`, `1`, or `2` |
| **Retain** | Whether the broker should retain the last message |

#### Finding your Tasmota MQTT topics

In the Tasmota web UI, go to **Console**. When you toggle the device you will see log lines like:

```
MQT: stat/tasmota_[DEVICE_ID]/RESULT = {"POWER":"ON"}
MQT: stat/tasmota_[DEVICE_ID]/POWER = ON
```

The topics to use:
- **Command topic:** `cmnd/tasmota_[DEVICE_ID]/POWER`
- **Status topic:** `stat/tasmota_[DEVICE_ID]/POWER`

Example output config for a Tasmota device controlled via Home Assistant MQTT:

```toml
[[outputs]]
name = "my-mqtt-device"
enabled = true
type = "threshold_mqtt"
input_name = "volume-prostate"
on_pause = "force_off"
on_disconnect = "force_off"
on_missing_input = "force_off"

[outputs.threshold]
threshold = 50.0
active_high = true
hysteresis = 20.0

[outputs.mqtt]
broker_host = "[homeassistant-hostname-or-ip]"
broker_port = 1883
username = "[mqtt-username]"
password = "[mqtt-password]"
command_topic = "cmnd/tasmota_[DEVICE_ID]/POWER"
payload_on = "ON"
payload_off = "OFF"
status_topic = "stat/tasmota_[DEVICE_ID]/POWER"
qos = 2
retain = true
```

---

## Configuration file

Configuration is stored at:

```
%APPDATA%\funscript-gateway\config.toml
```

It is written automatically by the UI. You can also edit it manually — the app reloads it on next start.

---

## Logging

Log files are written to:

```
%APPDATA%\funscript-gateway\logs\funscript-gateway.log
```

Rotating logs, 1 MB per file, 5 backups kept. Run with `--debug` for verbose output.

---

## Building from source

Requires Python 3.11+ and PyInstaller:

```bash
pip install -e ".[dev]"
python scripts/build.py
```

Produces `dist/funscript-gateway.exe`.
