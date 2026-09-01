# funscript-gateway — Release Notes

---

## v0.4.0

### Fixes

#### Cross-platform config location
The config directory now follows platform conventions instead of always using
the Windows `%APPDATA%` layout:

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\funscript-gateway\` (unchanged) |
| macOS | `~/Library/Application Support/funscript-gateway/` |
| Linux | `$XDG_CONFIG_HOME/funscript-gateway/` (`~/.config/funscript-gateway/` by default) |

A directory left by an older build in the home folder (`~/funscript-gateway`)
is migrated to the new location automatically on first launch. `config.toml`,
`funscript_gateway.log`, and `data_log/` all move together.

#### "Open log folder" button works on Linux and macOS
The button used the Windows-only `os.startfile`, so it silently did nothing on
other platforms. It now uses `QDesktopServices.openUrl`, which opens the
folder in the platform file manager everywhere.

### New

#### Linux AppImage
Releases now include `funscript-gateway-x86_64.AppImage` alongside the Windows
`.exe`. Built by `scripts/build_appimage.py` and by the release workflow on
Ubuntu 22.04.

---

## v0.3.0

### New features

#### Restim Volume input
A new input type that reads the current volume from restim's HTTP status endpoint and maps it to a 0–100 value. Useful for driving outputs in proportion to restim's volume rather than its playing state.

Three volume sources are available:

| Source | Description |
|--------|-------------|
| `ui` | Application volume slider (always present) |
| `device` | Hardware device volume (may be absent) |
| `multiply` | `ui × device` — both must be present |

A configurable fallback value is used when the endpoint is unreachable or the chosen source is absent. Poll interval is configurable separately from the Restim input.

#### Calculated (Logical) — per-entry inversion
Each entry in a Calculated (Logical) input now has an **inv** checkbox. When checked, the effective value used for threshold comparison becomes `100 − value` before applying the ≥/< test. This allows conditions like "input is mostly off" without needing a separate arithmetic step. The formula display in the dialog updates live to show the inversion.

#### Calculated (Arithmetic) — multiply mode and per-entry inversion
The Arithmetic input has two new capabilities:

**Operation selector** (`average` / `multiply`):
- `average` — existing weighted mean: `Σ(value × weight) ÷ Σ(weight)`
- `multiply` — product mode: `(v₁/100) × (v₂/100) × … × 100`

In multiply mode the weight spinner is disabled (weights don't apply). The formula display adapts to show the correct expression for the chosen operation.

**Per-entry inversion**: each entry also gets an **inv** checkbox, making the effective value `100 − value` before it enters the calculation. Works in both average and multiply modes.

#### Session correlation report
A self-contained HTML tool (`src/funscript_gateway/report/correlation_report.html`) for exploring CSV log files produced by the data logger. Drop or open a session CSV to get:

- **Full correlation matrix** — Pearson r heatmap across all numeric columns; click any cell to open a scatter plot with regression line and fit summary
- **HR Focus** — horizontal bar chart of all correlations with the heart rate BPM column, sorted by strength, click for scatter
- **Volume & Sensor Focus** — sub-matrix filtered to volume, AS5311, HR, restim, and pressure columns
- **Time Series** — overlaid line chart with per-column toggles, optional 0–1 normalization, wall-clock or player-position X axis, and automatic subsampling for large files

The file groups rows by `player_file` when multiple media files appear in a session, letting you filter the analysis to a specific file.

No server required — open directly in any browser.

### Bug fixes

#### WebSocket output crash on player disconnect
When a player disconnected, the disconnect handler called `set_state(bool)` on every output driver. `WsDriver` was missing this method, causing a `'WsDriver' object has no attribute 'set_state'` error logged for every WebSocket output. The handler now works correctly: `True` maps to full output (100) and `False` maps to off (0).

#### App freeze when CSV logging is active
The CSV data logger called `writer.writerow()` and `fh.flush()` directly on the asyncio event loop thread. On a slow or briefly busy disk (spinning drive, antivirus scan, network path) these blocking calls stalled the entire event loop, freezing the UI. The write and flush are now executed in a thread pool worker via `run_in_executor` so disk latency cannot block the UI.

---

## v0.2.0

### Bug fixes

#### Frozen player detected as paused
HereSphere (and any other player) can become frozen while still reporting a playing state — the player status shows connected and playing, but the playback position stops advancing. The gateway now monitors the timestamp on every state update; if the position has not moved for 5 seconds while the player claims to be playing, it is treated as paused. This prevents outputs from continuing to fire during a freeze.

---

## v0.1.10

### New features

#### Data logging
A new optional CSV logger records all inputs, outputs, and player state at a configurable sample interval. Enable it in **Settings → Data Logging**.

Each session produces a timestamped file:

```
%APPDATA%\funscript-gateway\data_log\session_YYYYMMDD_HHMMSS.csv
```

The file uses wide format — one row per sample, one column per signal — so the data can be loaded directly into pandas, Excel, or any analysis tool and columns can be correlated without reshaping.

**Columns per row:**

| Column | Description |
|--------|-------------|
| `timestamp` | ISO 8601 datetime with millisecond precision |
| `wall_time_s` | Unix timestamp as a float (useful for arithmetic) |
| `player_state` | Connection state name (e.g. `CONNECTED_AND_PLAYING`) |
| `player_file` | Filename of the currently loaded media (basename only) |
| `player_time_ms` | Current playback position in milliseconds |
| `player_speed` | Playback speed multiplier |
| `{name}_pct` | Input value 0–100 for each configured input |
| `{name}_mm` | Raw position in mm (AS5311 inputs only) |
| `{name}_bpm` | Raw BPM reading (Heart Rate inputs only) |
| `{name}_in` | Input value seen by each output at sample time |
| `{name}_out` | Output state at sample time: `1` = ON, `0` = OFF |

When a Funscript Axis input has no file for the current video (`file_missing = True`), its `_pct` cell is left empty rather than writing the default value — making "no data" clearly distinguishable from an actual zero in the funscript.

**Settings:**

| Setting | Description |
|---------|-------------|
| Enable checkbox | Turns logging on/off; takes effect immediately when Applied |
| Sample interval | How often to write a row (0.1–60 s, default 1.0 s) |
| Open log folder | Opens `%APPDATA%\funscript-gateway\data_log\` in Explorer |

The column layout is fixed when a session file is opened (based on the inputs and outputs present at that moment). If you add new inputs or outputs, click Apply in Settings to start a new session file that includes them.

#### Auto-discovered Funscript Axis inputs start disabled
Previously, when the Funscript Engine discovered axis files for a new video that weren't already in the inputs list, it created the new inputs with `enabled = True`. This meant they could inadvertently start driving outputs. Auto-discovered inputs are now created with `enabled = False` — they appear in the Inputs tab for review and can be enabled explicitly.

---

## v0.1.9

### Bug fixes

#### `on_pause` now applies to all input types
Previously the output's **On pause** setting was silently ignored for any non-Funscript-Axis input (Restim, Calculated — Logical and Arithmetic, AS5311, Tasmota, Heart Rate). Those inputs were treated as "always active regardless of player state", so an output with `on_pause = force_off` would remain on when the player was paused or had no file loaded. The evaluation loop now applies the `on_pause` behavior for all input types when the player is not playing, consistent with how Funscript Axis inputs behave.

`on_disconnect` was not affected — it already applied to all output types.

#### Per-player host address
The **Host** field in **Settings → Player Settings** is now stored separately for HereSphere and MPC-HC. Previously a single shared field was used, so switching player type would show (and on Apply, overwrite) the other player's address. Each player type now remembers its own host. Switching the type combo live-swaps the displayed address; both are preserved on Apply.

Existing config files using the old single `host` key are automatically migrated — the value is used as the initial address for both player types.

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
