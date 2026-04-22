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
Video player ──► funscript-gateway ──► evaluates funscript axis value at current timestamp
                                    └──► applies threshold + hysteresis ──► ON / OFF
                                                                         └──► Tasmota HTTP
                                                                         └──► MQTT publish
```

1. The player reports its current playback position.
2. The gateway looks up the funscript file for the configured axis (e.g. `myvideo.volume.funscript`).
3. Every 50 ms it interpolates the axis value (0–100) at the current timestamp.
4. Each output has a threshold processor: if the value crosses the threshold (with optional hysteresis), it sends ON or OFF to the device.

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

## Axes

In the **Axes** tab, add named axes that correspond to the `.funscript` file suffix. Each axis can be enabled or disabled independently. If the funscript file for an active axis is not found alongside the current video, each output's *On missing axis* behaviour applies.

---

## Outputs

Each output maps one axis to one device. Add outputs in the **Outputs** tab.

### Common settings

| Setting | Description |
|---------|-------------|
| **Name** | Display name |
| **Axis** | Which axis value to read |
| **Enabled** | Toggle without deleting |
| **On pause** | What to do when playback is paused: `hold` (keep last state), `force_off`, `force_on` |
| **On disconnect** | What to do when the player disconnects: `hold`, `force_off`, `force_on` |
| **On missing axis** | What to do when no funscript file is found for this axis: `hold`, `force_off`, `force_on` |

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
axis_name = "volume"
on_pause = "hold"
on_disconnect = "force_off"
on_missing_axis = "force_off"

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
axis_name = "volume-prostate"
on_pause = "force_off"
on_disconnect = "force_off"
on_missing_axis = "force_off"

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
