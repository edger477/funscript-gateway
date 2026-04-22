# funscript-gateway — Technical Specification

**Version:** 0.1.1  
**Date:** 2026-04-11  
**Status:** Draft

---

## Table of Contents

1. [Overview and Purpose](#1-overview-and-purpose)
2. [Technology Stack](#2-technology-stack)
3. [Architecture Overview](#3-architecture-overview)
4. [Player Integration](#4-player-integration)
   - 4.1 [HereSphere Protocol](#41-heresphere-protocol)
   - 4.2 [MPC-HC Protocol](#42-mpc-hc-protocol)
   - 4.3 [Player Connection Manager](#43-player-connection-manager)
5. [Funscript Axis System](#5-funscript-axis-system)
   - 5.1 [File Discovery](#51-file-discovery)
   - 5.2 [Funscript Parsing](#52-funscript-parsing)
   - 5.3 [Value Interpolation](#53-value-interpolation)
6. [Output System](#6-output-system)
   - 6.1 [Plugin Architecture](#61-plugin-architecture)
   - 6.2 [Threshold Switch Logic](#62-threshold-switch-logic)
   - 6.3 [Tasmota Device Driver](#63-tasmota-device-driver)
   - 6.4 [MQTT Switch Driver](#64-mqtt-switch-driver)
   - 6.5 [Output Evaluation Loop](#65-output-evaluation-loop)
7. [Configuration Persistence](#7-configuration-persistence)
8. [User Interface](#8-user-interface)
   - 8.1 [System Tray](#81-system-tray)
   - 8.2 [Main Window Layout](#82-main-window-layout)
   - 8.3 [Status Tab](#83-status-tab)
   - 8.4 [Axes Tab](#84-axes-tab)
   - 8.5 [Outputs Tab](#85-outputs-tab)
   - 8.6 [Settings Tab](#86-settings-tab)
9. [Key Data Structures](#9-key-data-structures)
10. [Error Handling and Edge Cases](#10-error-handling-and-edge-cases)
11. [Threading and Event Loop Model](#11-threading-and-event-loop-model)
12. [Future Extension Points](#12-future-extension-points)
13. [Project Layout](#13-project-layout)

---

## 1. Overview and Purpose

`funscript-gateway` is a desktop bridge service that connects video players — which play media files alongside `.funscript` haptic script files — to smart home devices and IoT outputs. The application runs as a Windows system tray service, monitors a running video player in real-time, reads the appropriate funscript data at the current playback position, and drives configurable outputs such as Tasmota smart switches or MQTT-controlled devices.

The primary inspiration is the [restim](https://github.com/diglet48/restim) project, which uses a similar player connection model. The player protocol implementations and funscript axis naming convention used here are derived from restim's approach.

### Core Data Flow

```
Video Player
     |
     | (HereSphere TCP / MPC-HC HTTP polling)
     v
Player Connection Manager
     |
     | PlayerState { current_time, is_playing, file_path }
     v
Funscript Engine
     |
     | axis_name -> interpolated value (0-100) at current_time
     v
Output Evaluation Loop  (20 Hz, every 50 ms)
     |
     | per-output: threshold logic -> device driver
     v
Device Drivers
  - Tasmota HTTP API
  - MQTT broker publish
```

---

## 2. Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.11+ | asyncio maturity, ecosystem for HTTP/MQTT, rapid development |
| GUI framework | PySide6 (Qt 6) | Native system tray support, cross-platform, good async integration |
| Event loop | `asyncio` + `qasync` | Bridges Qt event loop with asyncio; allows `async/await` throughout |
| HTTP client | `urllib.request` (stdlib) via `asyncio.to_thread` | Avoids aiohttp's `add_reader`/`add_writer` calls, which are not implemented on Windows `ProactorEventLoop` |
| MQTT client | `paho-mqtt` threaded loop (`loop_start`/`loop_stop`) | paho manages its own network thread; no asyncio socket integration, fully compatible with Windows `ProactorEventLoop` |
| Config format | TOML (`tomllib` stdlib + `tomli_w`) | Human-readable, stdlib read support in Python 3.11+ |
| Packaging | `pyproject.toml` + optional PyInstaller | Single-binary distribution for Windows |

### Dependency Summary

```toml
# pyproject.toml [project.dependencies]
dependencies = [
    "PySide6>=6.6",
    "qasync>=0.27",
    "paho-mqtt>=1.6",
    "tomli_w>=1.0",   # TOML write (stdlib only covers read in 3.11)
]
```

### Windows ProactorEventLoop compatibility note

`qasync` on Windows wraps `ProactorEventLoop`, which does **not** implement `add_reader` or `add_writer`. Any library that calls these (including `aiohttp` and `aiomqtt`/`paho-mqtt` in asyncio mode) will raise `NotImplementedError` at runtime. The solution used throughout this project is:

- **HTTP** (`TasmotaDriver`, `MpcHcBackend`): blocking `urllib.request` calls wrapped with `asyncio.to_thread`.
- **MQTT** (`MqttDriver`): paho-mqtt's own background network thread (`loop_start`/`loop_stop`), which does not touch the asyncio event loop's socket layer.

No third-party funscript or player-protocol libraries are used. All protocol handling is implemented directly, following the restim reference.

---

## 3. Architecture Overview

The application is structured as a set of cooperating components sharing a central `AppState` object. All I/O is async; the UI runs on the Qt main thread and receives updates via Qt signals emitted from asyncio callbacks.

```
main.py
  └── App (QApplication + asyncio event loop via qasync)
        ├── SystemTrayIcon
        ├── MainWindow
        │     ├── StatusTab
        │     ├── AxesTab
        │     ├── OutputsTab
        │     └── SettingsTab
        ├── PlayerConnectionManager      (asyncio task)
        │     ├── HereSphereBackend
        │     └── MpcHcBackend
        ├── FunscriptEngine              (synchronous, called from async context)
        └── OutputManager               (asyncio task, 20 Hz loop)
              ├── ThresholdSwitchProcessor
              ├── TasmotaDriver          (async HTTP)
              └── MqttDriver             (async MQTT)
```

Communication between async tasks and the Qt UI uses Qt signals. Async tasks call `signal.emit(...)` which is thread-safe in PySide6 when invoked from the Qt thread (asyncio runs on the same thread via `qasync`).

---

## 4. Player Integration

### 4.1 HereSphere Protocol

HereSphere exposes a TCP socket server. The gateway acts as a client.

**Connection parameters (defaults):**

| Parameter | Default |
|-----------|---------|
| Host | `127.0.0.1` |
| Port | `23554` |

**Wire format:**

Every message in both directions is framed with a 4-byte little-endian unsigned integer header indicating the byte length of the following JSON payload.

```
[4 bytes: LE uint32 length][N bytes: UTF-8 JSON]
```

Keep-alive: HereSphere sends a raw null byte (`0x00`) every ~1000 ms when idle. The client must tolerate receiving a single `0x00` byte that does not constitute a valid length header — this byte should be discarded.

**Received JSON fields:**

```json
{
  "playerState": 0,
  "currentTime": 42.317,
  "path": "C:/Videos/example.mp4",
  "playbackSpeed": 1.0
}
```

| Field | Type | Notes |
|-------|------|-------|
| `playerState` | int | `0` = playing; other values indicate paused/stopped (treat non-zero as not playing) |
| `currentTime` | float | Playback position in seconds |
| `path` | string | Absolute path to the media file currently loaded |
| `playbackSpeed` | float | Playback rate multiplier; `1.0` is normal speed |

**Reading loop pseudocode:**

```python
async def _read_loop(self, reader: asyncio.StreamReader):
    while True:
        header = await reader.readexactly(4)
        if header == b'\x00\x00\x00\x00':
            # keep-alive null frame, discard
            continue
        length = struct.unpack('<I', header)[0]
        if length == 0:
            continue
        data = await reader.readexactly(length)
        payload = json.loads(data.decode('utf-8'))
        self._handle_payload(payload)
```

**State derivation:**

```python
def _derive_state(self, payload: dict) -> MediaConnectionState:
    if payload.get('path') in (None, ''):
        return MediaConnectionState.CONNECTED_BUT_NO_FILE_LOADED
    if payload.get('playerState') == 0:
        return MediaConnectionState.CONNECTED_AND_PLAYING
    return MediaConnectionState.CONNECTED_AND_PAUSED
```

### 4.2 MPC-HC Protocol

MPC-HC exposes a minimal HTTP server. The gateway polls it at a configurable interval.

**Connection parameters (defaults):**

| Parameter | Default |
|-----------|---------|
| Host | `127.0.0.1` |
| Port | `13579` |
| Poll interval | `150 ms` |



**Endpoint:**

```
GET http://{host}:{port}/variables.html
```

The response is an HTML document. The relevant values are embedded as HTML content and must be extracted with regex. MPC-HC does not provide a JSON endpoint.

**Regex patterns (applied to response body):**

```python
RE_STATE        = re.compile(r'id="state"[^>]*>(-?\d+)<')
RE_FILEPATH     = re.compile(r'id="filepath"[^>]*>([^<]*)<')
RE_POSITION     = re.compile(r'id="position"[^>]*>(\d+)<')
RE_PLAYBACKRATE = re.compile(r'id="playbackrate"[^>]*>([0-9.]+)<')
```

**Parsed fields:**

| HTML id | Type | Notes |
|---------|------|-------|
| `state` | int | `2` = playing, `-1` = no file loaded, other = paused |
| `filepath` | string | Absolute path to the current file |
| `position` | int | Playback position in **milliseconds** |
| `playbackrate` | float | Playback speed multiplier |

Note: position from MPC-HC is in milliseconds; HereSphere uses seconds. The internal `PlayerState.current_time_ms` field always stores milliseconds to normalise across backends.

**State derivation:**

```python
def _derive_state(self, state_val: int, filepath: str) -> MediaConnectionState:
    if state_val == -1 or not filepath:
        return MediaConnectionState.CONNECTED_BUT_NO_FILE_LOADED
    if state_val == 2:
        return MediaConnectionState.CONNECTED_AND_PLAYING
    return MediaConnectionState.CONNECTED_AND_PAUSED
```

### 4.3 Player Connection Manager

The `PlayerConnectionManager` is responsible for:

1. Maintaining a persistent connection (or polling session) to the configured player backend.
2. Retrying connection every 5 seconds on failure.
3. Publishing `PlayerState` updates to the rest of the application via a Qt signal or asyncio queue.

**Interface:**

```python
class PlayerConnectionManager:
    # Emitted whenever player state changes
    state_changed: Signal(PlayerState)

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
```

**Retry logic:**

On any connection error (TCP refused, HTTP timeout, parse failure), the manager transitions to `NOT_CONNECTED`, waits 5 seconds, then attempts reconnection. A configurable maximum retry count of `0` (infinite) is the default.

**Backend selection:**

The active backend is determined by `GatewayConfig.player.type` (`"heresphere"` or `"mpc_hc"`). Switching backends requires stopping the current backend task and starting the new one.

---

## 5. Funscript Axis System

### 5.1 File Discovery

Funscript files follow the naming convention derived from restim:

```
{video_basename}.{axisname}.funscript
```

Examples for a file `C:/Videos/example.mp4`:

| Axis name | Expected filename |
|-----------|-------------------|
| `vibration` | `example.vibration.funscript` |
| `stroke` | `example.stroke.funscript` |
| `twist` | `example.twist.funscript` |

When `PlayerState.file_path` changes to a new non-empty value, the `FunscriptEngine` performs automatic discovery:

1. Extract the directory and base name (without extension) from `file_path`.
2. Glob for `{basename}.*.funscript` in the same directory.
3. For each match, parse the axis name from the filename segment between the first and last `.`.
4. Create `FunscriptAxis` entries for each discovered file.
5. Emit an `axes_updated` signal with the new axis list.

If a previously loaded file path changes, the old axes are cleared before discovery runs.

**Additional search paths:** Users may configure extra directories to search (e.g., a dedicated funscript library folder). Discovery checks the video's own directory first, then each additional search path in order, matching against the same basename pattern.

**Manual axis management:** The user may:
- Add an axis manually by specifying a name and file path.
- Remove any axis (auto-discovered or manual).
- Re-order axes (affects display only).

### 5.2 Funscript Parsing

A funscript file is a UTF-8 JSON document:

```json
{
  "actions": [
    {"at": 0,    "pos": 0},
    {"at": 1000, "pos": 75},
    {"at": 2500, "pos": 20},
    {"at": 3200, "pos": 100}
  ]
}
```

| Field | Type | Notes |
|-------|------|-------|
| `at` | int | Timestamp in milliseconds |
| `pos` | int | Position value, range 0–100 inclusive |

**Loading:**

```python
def load(self, path: str) -> list[tuple[int, int]]:
    """Returns sorted list of (at_ms, pos) tuples."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    actions = [(a['at'], a['pos']) for a in data['actions']]
    actions.sort(key=lambda x: x[0])
    return actions
```

The sorted action list is stored in memory for the lifetime of the axis. Files are re-read when the user explicitly refreshes or when the video changes.

### 5.3 Value Interpolation

Given a playback position `t_ms` and the sorted action list, the current value is computed using **linear interpolation** between the two surrounding keyframes.

```python
def interpolate(actions: list[tuple[int, int]], t_ms: int) -> float:
    """
    Returns interpolated position value (0.0–100.0) at t_ms.
    Clamps to first/last keyframe value if t_ms is out of range.
    """
    if not actions:
        return 0.0

    # Before first keyframe
    if t_ms <= actions[0][0]:
        return float(actions[0][1])

    # After last keyframe
    if t_ms >= actions[-1][0]:
        return float(actions[-1][1])

    # Binary search for surrounding pair
    lo, hi = 0, len(actions) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if actions[mid][0] <= t_ms:
            lo = mid
        else:
            hi = mid

    t0, p0 = actions[lo]
    t1, p1 = actions[hi]
    alpha = (t_ms - t0) / (t1 - t0)
    return p0 + alpha * (p1 - p0)
```

The result is a `float` in the range `[0.0, 100.0]`. Downstream consumers (output processors) receive this float directly.

---

## 6. Output System

### 6.1 Plugin Architecture

The output system separates two concerns:

- **Signal processors**: transform a funscript axis value (0–100 float) into a discrete state (on/off, or a normalised 0–1 float for future analog outputs).
- **Device drivers**: receive a state change command and deliver it to a physical or virtual device.

This separation allows any signal processor to be combined with any device driver. The current implemented combination is **Threshold → (Tasmota | MQTT)**.

```
FunscriptAxis.value (float 0-100)
        |
        v
  SignalProcessor          (e.g., ThresholdSwitchProcessor)
        |
        v
  bool: on / off
        |
        v
  DeviceDriver             (e.g., TasmotaDriver, MqttDriver)
```

An `OutputInstance` pairs one `SignalProcessor` with one `DeviceDriver`:

```python
@dataclass
class OutputInstance:
    config: OutputConfig          # contains both processor and driver config
    processor: SignalProcessor    # stateful: tracks last state for hysteresis
    driver: DeviceDriver          # stateful: tracks last sent state to avoid redundant calls
    last_input_value: float = 0.0
    last_output_state: bool = False
    consecutive_errors: int = 0   # resets to 0 on any successful driver call
    is_degraded: bool = False     # set True when consecutive_errors >= 3; cleared on success
```

### 6.2 Threshold Switch Logic

The `ThresholdSwitchProcessor` converts a continuous 0–100 value into a boolean on/off state.

**Configuration:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `threshold` | float | `50.0` | Crossover point (0–100) |
| `active_high` | bool | `True` | If True, on when value >= threshold; if False, on when value < threshold |
| `hysteresis` | float | `0.0` | Dead band around threshold to prevent rapid toggling |

**Logic with hysteresis:**

```
active_high = True, threshold = 50, hysteresis = 5
  → upper edge = 55, lower edge = 45

  current_state=False: switch to True  when value >= 55
  current_state=True:  switch to False when value <  45
  (values between 45 and 55 hold the current state)
```

**Implementation:**

```python
class ThresholdSwitchProcessor:
    def __init__(self, config: ThresholdSwitchConfig):
        self.config = config
        self._current_state: bool = False

    def process(self, value: float) -> bool:
        cfg = self.config
        half = cfg.hysteresis / 2.0

        if self._current_state:
            # Currently ON: switch off when value falls below lower edge
            switch_off = cfg.threshold - half
            if value < switch_off:
                self._current_state = False
        else:
            # Currently OFF: switch on when value rises above upper edge
            switch_on = cfg.threshold + half
            if value >= switch_on:
                self._current_state = True

        return self._current_state if cfg.active_high else not self._current_state
```

### 6.3 Tasmota Device Driver

The `TasmotaDriver` controls a Tasmota-flashed smart relay via its HTTP command interface.

**Configuration:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | str | — | IP address or hostname of the Tasmota device |
| `device_index` | int | `1` | Power channel index (1–8); use 1 for single-channel devices |
| `timeout_s` | float | `3.0` | HTTP request timeout in seconds |
| `repeat_interval_s` | int | `0` | When > 0, re-sends the ON command every N seconds while the output is active. Required for pulse-mode devices (see below). `0` = disabled. |

**Pulse mode keep-alive:**

Tasmota supports a hardware-safe auto-off timer called *PulseTime*. When configured (e.g. `PulseTime1 160` in the Tasmota console = auto-off after 60 s), the relay returns to OFF on its own if it stops receiving renewal commands — protecting against network failures or application crashes.

When using pulse mode, set `repeat_interval_s` to a value shorter than the pulse duration so the driver continuously renews the ON command while the output is active. Example: `PulseTime1 160` (60 s timeout) → set `repeat_interval_s = 45`.

PulseTime encoding: values 112–65535 encode seconds as `value − 100`, so `PulseTime 160 = 60 s`, `PulseTime 130 = 30 s`.

**Tasmota HTTP API:**

```
# Send command
GET http://{host}/cm?cmnd=Power{index}%20{On|Off}

# Query current state
GET http://{host}/cm?cmnd=Power{index}

# Example: turn on channel 1
GET http://192.168.1.42/cm?cmnd=Power1%20On

# Example: turn off channel 2
GET http://192.168.1.42/cm?cmnd=Power2%20Off
```

**Response format (JSON):**

```json
{"POWER1": "ON"}
```

The driver sends commands only when the desired state differs from the last successfully acknowledged state, to avoid flooding the device.

**Implementation sketch:**

```python
import time
import urllib.request

class TasmotaDriver:
    def __init__(self, config: TasmotaOutputConfig) -> None:
        self.config = config
        self._last_sent: bool | None = None
        self._last_send_time: float = 0.0

    async def set_state(self, on: bool) -> None:
        repeat = self.config.repeat_interval_s
        now = time.monotonic()

        if on == self._last_sent:
            # Re-send ON if repeat interval elapsed; always skip OFF repeats.
            if not on or repeat <= 0 or (now - self._last_send_time) < repeat:
                return

        cmd = "On" if on else "Off"
        url = (
            f"http://{self.config.host}/cm"
            f"?cmnd=Power{self.config.device_index}%20{cmd}"
        )
        timeout = self.config.timeout_s

        def do_request() -> None:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                resp.read()

        await asyncio.to_thread(do_request)
        self._last_sent = on
        self._last_send_time = now
```

`asyncio.to_thread` offloads the blocking `urllib.request` call to a thread pool worker, keeping the asyncio event loop unblocked. On HTTP error the exception propagates to the evaluation loop, `_last_sent` and `_last_send_time` are not updated, and the next cycle will retry.

### 6.4 MQTT Switch Driver

The `MqttDriver` publishes on/off messages to an MQTT broker using paho-mqtt's threaded network loop.

**Configuration:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `broker_host` | str | — | MQTT broker hostname or IP |
| `broker_port` | int | `1883` | MQTT broker port |
| `username` | str | `""` | Broker username (empty = anonymous) |
| `password` | str | `""` | Broker password |
| `command_topic` | str | — | Topic to publish commands to |
| `payload_on` | str | `"ON"` | Payload string for the on state |
| `payload_off` | str | `"OFF"` | Payload string for the off state |
| `status_topic` | str | `""` | Optional topic to subscribe for state confirmation |
| `qos` | int | `0` | MQTT QoS level (0, 1, or 2) |
| `retain` | bool | `False` | Whether to set the MQTT retain flag |

**Lifecycle:**

Each `MqttDriver` owns one `paho.mqtt.client.Client` instance. The lifecycle is:

```
await driver.connect()    # blocks in asyncio.to_thread until connected (10 s timeout)
await driver.set_state()  # thread-safe publish via paho's internal queue (non-blocking)
await driver.disconnect() # stops background thread, disconnects
```

`connect()` calls `client.loop_start()`, which starts paho's own background network thread. This thread handles all socket I/O independently of the asyncio event loop — no `add_reader`/`add_writer` calls are made.

**Publish logic:**

```python
class MqttDriver:
    async def set_state(self, on: bool) -> None:
        if on == self._last_sent:
            return
        payload = self.config.payload_on if on else self.config.payload_off
        result = self._client.publish(
            self.config.command_topic,
            payload,
            qos=self.config.qos,
            retain=self.config.retain,
        )
        if result.rc != paho.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish error rc={result.rc}")
        self._last_sent = on
```

`paho.publish()` is thread-safe: it queues the message internally and the background thread sends it. The call returns immediately.

**Status topic:**

If `status_topic` is configured, the driver subscribes on connect via `on_connect` callback and updates an internal `_confirmed_state: bool | None` attribute when a matching payload is received via `on_message`. This state is available for UI monitoring but does not affect command logic.

**Connection failure handling:**

If the broker is unreachable, `connect()` waits up to 10 seconds for `on_connect` to fire. On timeout, `loop_stop()` is called and a `ConnectionError` is raised. The `OutputManager` catches this, logs a warning, and leaves the output inactive (driver set to `None`). The output will remain inactive until the user triggers a reload via the UI.

### 6.5 Output Evaluation Loop

The `OutputManager` runs a single asyncio task that evaluates all configured outputs at 20 Hz (every 50 ms).

```python
async def _evaluation_loop(self) -> None:
    while self._running:
        start = asyncio.get_event_loop().time()

        player_state = self._app_state.player_state
        is_playing = (
            player_state.connection_state == MediaConnectionState.CONNECTED_AND_PLAYING
        )

        for output in self._outputs:
            if not output.config.enabled:
                continue

            if output.driver is None:
                continue

            axis = self._resolve_axis(output.config.axis_name)
            axis_available = (
                axis is not None and axis.enabled and not axis.file_missing
            )

            if not axis_available:
                forced = self._handle_missing_axis_behavior(output)
                if forced is None:
                    continue  # hold
                new_state = forced
            elif is_playing:
                new_state = output.processor.process(axis.current_value)
                output.last_input_value = axis.current_value
            else:
                forced = self._handle_pause_behavior(output)
                if forced is None:
                    continue  # hold: no command sent
                new_state = forced

            output.last_output_state = new_state

            try:
                await output.driver.set_state(new_state)
                output.consecutive_errors = 0
                output.is_degraded = False
            except Exception as e:
                output.consecutive_errors += 1
                if output.consecutive_errors >= 3:
                    output.is_degraded = True
                logger.warning("Output '%s' driver error: %s", output.config.name, e)

        self._outputs_updated.emit()  # Qt signal for UI refresh

        elapsed = asyncio.get_event_loop().time() - start
        await asyncio.sleep(max(0.0, 0.050 - elapsed))
```

**On-pause behavior** is configurable per output and applied on every non-playing tick (not just on transition):

| Mode | Behavior |
|------|----------|
| `hold` | No command sent; output stays in whatever state it was last set to (default) |
| `force_off` | Send off state every tick while paused/stopped |
| `force_on` | Send on state every tick while paused/stopped |

```python
def _handle_pause_behavior(self, output: OutputInstance) -> bool | None:
    match output.config.on_pause:
        case "force_off": return False
        case "force_on":  return True
        case "hold":      return None   # caller skips driver call

def _handle_missing_axis_behavior(self, output: OutputInstance) -> bool | None:
    match output.config.on_missing_axis:
        case "force_off": return False
        case "force_on":  return True
        case "hold":      return None   # caller skips driver call
```

**On-disconnect behavior** is configurable per output and applies when `connection_state` transitions to `NOT_CONNECTED` (i.e., the player process is unreachable, TCP connection dropped, or polling fails):

| Mode | Behavior |
|------|----------|
| `hold` | No command sent; output retains whatever state it was in when connection was lost |
| `force_off` | Send off state on disconnect (default) |
| `force_on` | Send on state on disconnect |

The disconnect handler fires once on the transition into `NOT_CONNECTED`; it does not repeatedly fire while the player remains disconnected. A re-connection resets the transition flag.

```python
async def _handle_disconnect(self) -> None:
    for output in self._outputs:
        if not output.config.enabled:
            continue
        match output.config.on_disconnect:
            case "force_off": state = False
            case "force_on":  state = True
            case "hold":      continue
        try:
            await output.driver.set_state(state)
            output.last_output_state = state
        except Exception as e:
            logger.warning("Output '%s' disconnect handler error: %s", output.config.name, e)
```

The `_evaluation_loop` calls `_handle_disconnect` on the first tick where `connection_state == NOT_CONNECTED` after previously being in any connected state, tracked via a `_was_connected: bool` flag on `OutputManager`.

---

## 7. Configuration Persistence

Configuration is stored as a TOML file at:

```
Windows: %APPDATA%\funscript-gateway\config.toml
```

Resolved in Python as:

```python
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get('APPDATA', Path.home())) / 'funscript-gateway'
CONFIG_PATH = CONFIG_DIR / 'config.toml'
```

The directory is created on first run if it does not exist.

**Example `config.toml`:**

```toml
[player]
type = "heresphere"
host = "127.0.0.1"
port = 23554
poll_interval_ms = 150

[funscript]
search_paths = []

[[axes]]
name = "vibration"
file_path = "C:/Videos/example.vibration.funscript"
enabled = true

[[outputs]]
name = "Bed Vibrator"
enabled = true
type = "threshold_tasmota"
axis_name = "vibration"
on_pause = "force_off"
on_disconnect = "force_off"

  [outputs.threshold]
  threshold = 40.0
  active_high = true
  hysteresis = 5.0

  [outputs.tasmota]
  host = "192.168.1.42"
  device_index = 1
  timeout_s = 3.0
  repeat_interval_s = 0

[[outputs]]
name = "Atmosphere Light"
enabled = true
type = "threshold_mqtt"
axis_name = "stroke"
on_pause = "hold"
on_disconnect = "force_off"

  [outputs.threshold]
  threshold = 60.0
  active_high = true
  hysteresis = 0.0

  [outputs.mqtt]
  broker_host = "192.168.1.10"
  broker_port = 1883
  command_topic = "home/bedroom/light/set"
  payload_on = "ON"
  payload_off = "OFF"
  status_topic = "home/bedroom/light/state"
  qos = 1
  retain = false
```

**Startup sequence:**

1. Load `config.toml`; if missing, create a default config with no outputs.
2. Apply `player` settings to `PlayerConnectionManager`.
3. Restore `axes` list (manual entries only; auto-discovery runs when a player connects and reports a file).
4. Instantiate all `outputs`, creating processor and driver objects.
5. Start the player connection manager and output evaluation loop.

**Save triggers:**

- User clicks Save/Apply in the Settings tab.
- Any structural change in the Axes or Outputs tabs (add, remove, reorder).
- Application shutdown (graceful).

Configuration is written atomically: write to a temporary file, then rename to replace the existing config.

---

## 8. User Interface

### 8.1 System Tray

The application places an icon in the Windows system tray. The icon has two states:

| State | Icon appearance |
|-------|----------------|
| Connected and playing | Full-colour icon |
| Not connected / paused | Greyed-out icon |

**Tray context menu:**

```
Open funscript-gateway
──────────────────────
Quit
```

Double-clicking the tray icon opens or brings focus to the main window.

### 8.2 Main Window Layout

The main window is a fixed-size (or minimum-size) window with a tab widget containing four tabs. It can be hidden without closing (clicking the window close button minimises to tray).

```
┌─────────────────────────────────────────────────────────┐
│  funscript-gateway                              [_ □ ×]  │
├─────────────────────────────────────────────────────────┤
│  [Status]  [Axes]  [Outputs]  [Settings]                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  (tab content)                                          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 8.3 Status Tab

Displays live player connection state. Updates are driven by the `state_changed` signal from `PlayerConnectionManager`.

```
Connection:  ● CONNECTED AND PLAYING          (green indicator)
Player:      HereSphere  (127.0.0.1:23554)
File:        C:/Videos/example.mp4
Time:        00:01:42.317  (1x speed)
```

The connection indicator dot is:
- Green: `CONNECTED_AND_PLAYING`
- Yellow: `CONNECTED_AND_PAUSED` or `CONNECTED_BUT_NO_FILE_LOADED`
- Red: `NOT_CONNECTED`

### 8.4 Axes Tab

Displays all currently loaded funscript axes. Updated when axes are loaded/discovered and at the output loop tick (20 Hz) for live value bars.

**Table columns:**

| Column | Content |
|--------|---------|
| Enabled | Checkbox toggle |
| Name | Axis name string |
| File | Truncated file path; tooltip shows full path |
| Value | Live horizontal progress bar (0–100) + numeric label |
| Status | "OK" / "File missing" / "Not loaded" |

**Toolbar actions above the table:**

- **Refresh** — re-run auto-discovery for the current file
- **Add axis** — opens a dialog: enter name, select funscript file
- **Remove selected** — removes the selected axis

### 8.5 Outputs Tab

Displays all configured outputs. Updated at the 20 Hz loop tick.

**Table columns:**

| Column | Content |
|--------|---------|
| Enabled | Checkbox toggle |
| Name | Output name |
| Type | e.g., "Threshold → Tasmota" |
| Axis | Source axis name |
| Input | Current axis value (numeric, 0–100) |
| State | Current output state: ON (green) / OFF (grey) |

**Toolbar actions:**

- **Add output** — opens the output configuration dialog
- **Edit selected** — re-opens the configuration dialog for the selected output
- **Remove selected** — removes the selected output

**Output configuration dialog** is a two-panel form:
1. Left panel: output name, axis selection (dropdown of loaded axes), enabled checkbox, on-pause behavior, on-disconnect behavior, on-missing-axis behavior.
2. Right panel: tabbed sub-form for threshold config and device driver config (Tasmota or MQTT).

`on_pause` dropdown options: `hold` (default), `force_off`, `force_on`.
`on_disconnect` dropdown options: `force_off` (default), `hold`, `force_on`.
`on_missing_axis` dropdown options: `force_off` (default), `hold`, `force_on`.

### 8.6 Settings Tab

Form-based settings for the player connection.

```
Player Settings
───────────────
Player Type:     [HereSphere ▼]
Host:            [127.0.0.1      ]
Port:            [23554  ]

Funscript Paths
───────────────
Additional search paths:
  [ list widget with paths ]
  [+ Add path]  [- Remove]

                            [Apply]  [Cancel]
```

Apply writes the configuration to disk and triggers a reconnection if player settings changed.

---

## 9. Key Data Structures

All structures use Python `dataclasses` (or `@dataclass`) with default values where appropriate.

### `MediaConnectionState` Enum

```python
from enum import Enum, auto

class MediaConnectionState(Enum):
    NOT_CONNECTED               = auto()
    CONNECTED_BUT_NO_FILE_LOADED = auto()
    CONNECTED_AND_PAUSED        = auto()
    CONNECTED_AND_PLAYING       = auto()
```

### `PlayerState`

```python
from dataclasses import dataclass, field

@dataclass
class PlayerState:
    connection_state: MediaConnectionState = MediaConnectionState.NOT_CONNECTED
    file_path: str = ""
    current_time_ms: int = 0           # always milliseconds, normalised from backend
    playback_speed: float = 1.0
```

### `FunscriptAxis`

```python
@dataclass
class FunscriptAxis:
    name: str
    file_path: str
    enabled: bool = True
    actions: list[tuple[int, int]] = field(default_factory=list)  # (at_ms, pos)
    current_value: float = 0.0          # interpolated at current_time_ms
    file_missing: bool = False
```

### `PlayerConfig`

```python
@dataclass
class PlayerConfig:
    type: str = "heresphere"           # "heresphere" | "mpc_hc"
    host: str = "127.0.0.1"
    port: int = 23554
    poll_interval_ms: int = 150        # MPC-HC only; ignored by HereSphere (event-driven)
```

### Output Config Hierarchy

```python
from dataclasses import dataclass

# --- Signal processor configs ---

@dataclass
class ThresholdSwitchConfig:
    threshold: float = 50.0            # crossover point, 0-100
    active_high: bool = True           # True: ON when value >= threshold
    hysteresis: float = 0.0            # dead band (full width, ±hysteresis/2)

# --- Device driver configs ---

@dataclass
class TasmotaOutputConfig:
    host: str = ""
    device_index: int = 1
    timeout_s: float = 3.0
    repeat_interval_s: int = 0          # 0 = disabled; >0 = re-send ON every N seconds (pulse mode)

@dataclass
class MqttOutputConfig:
    broker_host: str = ""
    broker_port: int = 1883
    username: str = ""                 # empty string = anonymous
    password: str = ""
    command_topic: str = ""
    payload_on: str = "ON"
    payload_off: str = "OFF"
    status_topic: str = ""             # empty string = no status subscription
    qos: int = 0
    retain: bool = False

# --- Combined output config ---

from typing import Literal
from typing import Union

@dataclass
class OutputConfig:
    name: str = ""
    enabled: bool = True
    type: Literal["threshold_tasmota", "threshold_mqtt"] = "threshold_tasmota"
    axis_name: str = ""
    on_pause: Literal["hold", "force_on", "force_off"] = "hold"
    on_disconnect: Literal["hold", "force_on", "force_off"] = "force_off"
    on_missing_axis: Literal["hold", "force_on", "force_off"] = "force_off"
    threshold: ThresholdSwitchConfig = field(default_factory=ThresholdSwitchConfig)
    tasmota: TasmotaOutputConfig = field(default_factory=TasmotaOutputConfig)
    mqtt: MqttOutputConfig = field(default_factory=MqttOutputConfig)
```

### `GatewayConfig`

```python
@dataclass
class GatewayConfig:
    player: PlayerConfig = field(default_factory=PlayerConfig)
    funscript_search_paths: list[str] = field(default_factory=list)
    axes: list[FunscriptAxis] = field(default_factory=list)  # persisted manual entries
    outputs: list[OutputConfig] = field(default_factory=list)
```

### `AppState`

`AppState` is a `QObject` subclass that acts as the shared mutable hub for all runtime state. Components hold a reference to the single `AppState` instance created in `main.py`.

```python
from PySide6.QtCore import QObject, Signal

class AppState(QObject):
    # Emitted by PlayerConnectionManager whenever player state changes
    player_state_changed = Signal(PlayerState)
    # Emitted by FunscriptEngine when the axis list changes (file change, add, remove)
    axes_updated = Signal(list)          # list[FunscriptAxis]
    # Emitted by OutputManager at each 20 Hz tick for UI refresh
    outputs_updated = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.config: GatewayConfig = GatewayConfig()
        self.player_state: PlayerState = PlayerState()
        self.current_time_ms: int = 0    # authoritative playback position used by all consumers
        self.axes: list[FunscriptAxis] = []
        self.outputs: list[OutputInstance] = []
```

`current_time_ms` is the single source of truth for playback position. It is written by `PlayerConnectionManager` and read by `FunscriptEngine` and `OutputManager`.

---

## 10. Error Handling and Edge Cases

### Player Not Reachable

- `PlayerConnectionManager` catches `ConnectionRefusedError`, `asyncio.TimeoutError`, `urllib.error.URLError`, and `OSError`.
- Transitions state to `NOT_CONNECTED`.
- Waits 5 seconds, then retries.
- No crash, no user prompt — status tab reflects the disconnected state.

### Funscript File Not Found

- On axis load, if the file does not exist: set `FunscriptAxis.file_missing = True`, keep the axis in the list.
- Axes with `file_missing = True` report `current_value = 0.0`.
- The Axes tab shows "File missing" in the Status column, with the row highlighted in amber.
- If the file reappears (e.g., network share reconnects), a manual Refresh restores it.

### Player Disconnected

- On the first evaluation tick where `connection_state == NOT_CONNECTED` after previously being in any connected state (`CONNECTED_AND_PLAYING`, `CONNECTED_AND_PAUSED`, or `CONNECTED_BUT_NO_FILE_LOADED`):
  - For each output, apply `on_disconnect` behavior:
    - `force_off` (default): call `driver.set_state(False)`; update `last_output_state = False`.
    - `hold`: take no action; output retains its last state.
- The handler fires only once per disconnection event (on the transition edge), not on every tick while disconnected.
- `OutputManager` tracks a `_was_connected: bool` flag. It is set to `True` on any tick where the player is in a connected state, and to `False` after the disconnect handler has fired. It resets to `True` again as soon as a connected state is observed.
- Axis `current_value` values are left unchanged; they reflect the last known playback position and will be re-evaluated when the player reconnects.

### Playback Paused or Stopped

- While `connection_state` is `CONNECTED_AND_PAUSED` or `CONNECTED_BUT_NO_FILE_LOADED`, the evaluation loop applies `on_pause` per output on every tick:
  - `hold`: no command sent; output stays in its last state.
  - `force_off`: `driver.set_state(False)` called each tick (driver deduplicates if state unchanged).
  - `force_on`: `driver.set_state(True)` called each tick.
- Axis `current_value` is frozen at the last computed value while paused; it does not revert to 0.

### Missing or Unavailable Axis

Applies each evaluation tick when the output's assigned axis is not available — meaning the axis name is not in the axis list, the axis is disabled, or `file_missing = True`.

| Mode | Behavior |
|------|----------|
| `force_off` | Send off state each tick (default) |
| `force_on` | Send on state each tick |
| `hold` | No command sent; output retains its last state |

This is evaluated before `on_pause`: if the axis is missing, `on_missing_axis` applies regardless of whether the player is playing or paused.

### Player File Change

- When `PlayerState.file_path` changes (different from the previous non-empty value):
  - Clear all auto-discovered axes.
  - Run axis auto-discovery for the new file.
  - Manual axes (those added by the user via the Add dialog) are retained but re-validated.

### Application Shutdown

On graceful shutdown (user selects Quit from tray menu or OS close), the `OutputManager` runs the same `_handle_disconnect` logic before stopping — each output's `on_disconnect` behavior is applied. This ensures physical devices are left in the expected state even when the application exits normally.

Shutdown sequence:
1. Stop the output evaluation loop.
2. Call `_handle_disconnect` once (respects per-output `on_disconnect` setting).
3. Close MQTT client connections.
4. Stop `PlayerConnectionManager`.
5. Save configuration.
6. Exit.

### Output Driver Errors

- Device HTTP/MQTT errors are caught per-output in the evaluation loop.
- `OutputInstance.consecutive_errors` is incremented on each failure and reset to `0` on the next successful command.
- When `consecutive_errors >= 3`, `OutputInstance.is_degraded` is set to `True`; the Outputs tab shows a yellow indicator for that row.
- `is_degraded` is cleared (set to `False`) as soon as a command succeeds.
- All errors are written to the application log (see below).

### Application Logging

Log file location:

```
%APPDATA%\funscript-gateway\funscript_gateway.log
```

Configuration (in `main.py`):

```python
import logging
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    LOG_PATH,
    maxBytes=1 * 1024 * 1024,   # 1 MB per file
    backupCount=3,               # keep .log, .log.1, .log.2, .log.3
    encoding='utf-8',
)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(name)s: %(message)s',
    handlers=[handler],
)
```

All modules use `logger = logging.getLogger(__name__)`. Log level `INFO` in production; `DEBUG` enabled via a `--debug` CLI flag.

### Configuration Parse Error

- If `config.toml` is malformed on startup, log the error, show a non-blocking notification in the status tab, and fall back to a default in-memory config.
- The malformed file is backed up as `config.toml.bak` before being overwritten.

### Simultaneous Evaluation and Config Change

- Config changes (add/remove output, change axis mapping) happen on the Qt main thread.
- The output evaluation loop also runs on the main thread (via `qasync`).
- Since Python's asyncio is single-threaded, there is no race condition: evaluation awaits I/O, during which config modifications can be processed by the event loop.
- The `OutputManager` holds a direct reference to the list of `OutputInstance` objects; modifications replace this list atomically.

---

## 11. Threading and Event Loop Model

`funscript-gateway` uses a single Qt/asyncio main thread with `qasync`, plus two categories of background activity managed carefully to stay compatible with Windows `ProactorEventLoop`.

```
Main Thread
  Qt Event Loop (pumped by qasync)
    └── asyncio Event Loop
          ├── PlayerConnectionManager task
          │     └── MpcHcBackend: asyncio.to_thread → urllib.request (thread pool)
          ├── OutputManager evaluation loop (50 ms timer)
          │     └── TasmotaDriver: asyncio.to_thread → urllib.request (thread pool)
          └── MqttDriver connect/disconnect: asyncio.to_thread (thread pool)

Background Threads (managed by paho-mqtt, one per MqttDriver)
  paho network thread (loop_start) — socket send/recv for MQTT, no asyncio involvement
```

Qt signals are emitted from async callbacks on the main thread (safe because all Qt and asyncio code runs on one thread). Slot connections use the default `AutoConnection`.

**Concurrency model summary:**

- All Qt UI and asyncio logic runs on the main thread.
- Blocking HTTP calls (Tasmota, MPC-HC polling) are offloaded via `asyncio.to_thread` to Python's default thread pool. Results are awaited on the main thread.
- MQTT network I/O is handled by paho's own background thread (`loop_start`). The asyncio event loop never touches MQTT sockets directly. `asyncio.to_thread` is used only for the initial connect/disconnect handshake.
- `QThread` and `concurrent.futures` are not used directly.

---

## 12. Future Extension Points

The following areas are explicitly designed to be extensible without restructuring the core application.

### Additional Player Backends

Implement the `PlayerBackend` protocol:

```python
class PlayerBackend(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def read_state(self) -> PlayerState: ...
```

Register the new backend class in the player type registry keyed by a string identifier. Add the identifier to the player type dropdown in Settings.

Candidates: VLC (HTTP interface), Kodi (JSON-RPC), DeoVR (WebSocket).

### Additional Output Types

New output types add:
1. A new `*Config` dataclass for the driver configuration.
2. A new `DeviceDriver` implementation.
3. Registration in the output type registry.
4. A sub-form in the output configuration dialog.

Candidates:
- **PWM/analog outputs** via serial port (e.g., Arduino)
- **OSC** (Open Sound Control) for lighting/AV systems
- **WebSocket** push to browser-based receivers

### Additional Signal Processors

New signal processors implement:

```python
class SignalProcessor(Protocol):
    def process(self, value: float) -> bool: ...
```

Candidates:
- **Envelope follower**: smoothed output with attack/release times
- **Pattern generator**: ignores input value, drives output on a timed pattern when input exceeds a threshold
- **Multi-axis combiner**: takes two axis values and combines them (e.g., max, sum, product) before threshold

### Multi-Axis Math

An `AxisExpression` layer can be inserted between the raw axis list and the output assignment. An expression references one or more named axes and computes a derived value:

```
derived_value = max(axes["stroke"], axes["vibration"])
```

The `OutputConfig.axis_name` field would be extended to accept either a raw axis name or an expression name.

### Scripted Outputs (User Python Expressions)

A sandboxed `eval`-based processor that evaluates a user-supplied Python expression:

```python
# User expression string stored in config
"100 if value > 60 else 0"
```

Executed with a restricted namespace containing only `value` and standard math functions. Intended for power users, disabled by default.

---

## 13. Project Layout

```
funscript-gateway/
├── pyproject.toml
├── SPEC.md
├── src/
│   └── funscript_gateway/
│       ├── __init__.py
│       ├── main.py                  # Entry point: App, qasync setup
│       ├── app_state.py             # Shared mutable state, Qt signals hub
│       ├── config.py                # GatewayConfig, load/save TOML
│       ├── models.py                # All dataclasses and enums
│       ├── player/
│       │   ├── __init__.py
│       │   ├── manager.py           # PlayerConnectionManager
│       │   ├── heresphere.py        # HereSphere TCP backend
│       │   └── mpc_hc.py            # MPC-HC HTTP polling backend
│       ├── funscript/
│       │   ├── __init__.py
│       │   ├── engine.py            # FunscriptEngine: discovery, load, interpolate
│       │   └── parser.py            # JSON parsing, action list construction
│       ├── outputs/
│       │   ├── __init__.py
│       │   ├── manager.py           # OutputManager: evaluation loop
│       │   ├── threshold.py         # ThresholdSwitchProcessor
│       │   ├── tasmota.py           # TasmotaDriver
│       │   └── mqtt.py              # MqttDriver
│       └── ui/
│           ├── __init__.py
│           ├── main_window.py       # MainWindow, tab container
│           ├── tray.py              # SystemTrayIcon
│           ├── status_tab.py
│           ├── axes_tab.py
│           ├── outputs_tab.py
│           ├── settings_tab.py
│           └── output_dialog.py     # Add/Edit output dialog
└── tests/
    ├── test_interpolation.py
    ├── test_threshold.py
    ├── test_heresphere_protocol.py
    └── test_config.py
```

---

*End of specification.*
