"""All dataclasses and enums for funscript-gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Literal, Union

if TYPE_CHECKING:
    pass


class MediaConnectionState(Enum):
    NOT_CONNECTED = auto()
    CONNECTED_BUT_NO_FILE_LOADED = auto()
    CONNECTED_AND_PAUSED = auto()
    CONNECTED_AND_PLAYING = auto()


@dataclass
class PlayerState:
    connection_state: MediaConnectionState = MediaConnectionState.NOT_CONNECTED
    file_path: str = ""
    current_time_ms: int = 0
    playback_speed: float = 1.0


@dataclass
class FunscriptAxisInput:
    name: str
    enabled: bool = True
    default_value: float = 0.0  # 0.0–1.0; applied (×100) when file not found for current video
    # Runtime fields populated by FunscriptEngine (not persisted):
    file_path: str = ""
    actions: list[tuple[int, int]] = field(default_factory=list)
    current_value: float = 0.0
    file_missing: bool = False


# Backwards-compat alias used throughout the codebase
FunscriptAxis = FunscriptAxisInput


@dataclass
class RestimCondition:
    playing: Literal["yes", "no", "any"] = "any"
    volume_ui_enabled: bool = False
    volume_ui_above: bool = True   # True = "above threshold"
    volume_ui_threshold: float = 0.5
    volume_device_enabled: bool = False
    volume_device_above: bool = True
    volume_device_threshold: float = 0.5


@dataclass
class RestimInput:
    name: str
    url: str = "http://localhost:12348/v1/status"
    enabled: bool = True
    poll_interval_s: float = 2.0
    default_value: bool = False  # on/off when endpoint is unavailable
    condition: RestimCondition = field(default_factory=RestimCondition)
    # Runtime fields (not persisted):
    current_value: float = 0.0  # 100.0 if condition met, 0.0 otherwise
    is_error: bool = False       # True when HTTP request failed


@dataclass
class CalculatedEntry:
    input_name: str
    operator: Literal["and", "or", "xor"] = "and"  # operator before this entry; ignored for first
    above: bool = True          # True: entry is ON when value >= threshold; False: when value < threshold
    threshold: float = 50.0    # 0–100 threshold for converting the input value to boolean


@dataclass
class CalculatedInput:
    name: str
    enabled: bool = True
    entries: list[CalculatedEntry] = field(default_factory=list)
    # Runtime:
    current_value: float = 0.0


@dataclass
class As5311Input:
    """AS5311 magnetic linear encoder input via restim WebSocket.

    Receives JSON messages ``{"x": <metres>}`` and maps position to 0–100.
    Positions below threshold_mm map to 0; positions above threshold_mm + range_mm
    map to 100; positions in between are interpolated linearly.
    Multiple inputs may share the same WebSocket URL — they share one connection.
    """
    name: str
    url: str = "ws://localhost:12346/sensors/as5311"
    enabled: bool = True
    threshold_mm: float = 0.0   # position (mm) that maps to 0
    range_mm: float = 2.0       # span (mm) from threshold to full scale (100)
    # Runtime fields (not persisted):
    current_value: float = 0.0
    last_position_mm: float = 0.0
    is_error: bool = False


@dataclass
class ArithmeticEntry:
    input_name: str
    multiplier: int = 1   # 1–4; output = Σ(value_i × mult_i) / Σ(mult_i)


@dataclass
class ArithmeticInput:
    name: str
    enabled: bool = True
    entries: list[ArithmeticEntry] = field(default_factory=list)
    # Runtime:
    current_value: float = 0.0


@dataclass
class TasmotaInput:
    """Polls a Tasmota device's power state via HTTP. Maps OFF→0, ON→100."""
    name: str
    host: str = ""
    device_index: int = 1
    poll_interval_s: float = 2.0
    timeout_s: float = 3.0
    enabled: bool = True
    # Runtime fields (not persisted):
    current_value: float = 0.0
    is_error: bool = False


@dataclass
class HeartRateInput:
    """BLE Heart Rate Profile sensor (chest strap or watch in broadcast mode).

    Subscribes to GATT characteristic 0x2A37 and maps BPM linearly to 0–100
    using configurable min/max BPM bounds.
    """
    name: str
    device_address: str = ""      # BLE address as reported by Windows (may be UUID on Win)
    device_label: str = ""        # human-readable device name (display only, not used for connection)
    enabled: bool = True
    scale_min_bpm: int = 40       # BPM that maps to output 0
    scale_max_bpm: int = 180      # BPM that maps to output 100
    # Runtime fields (not persisted):
    current_value: float = 0.0    # 0–100 scaled
    current_bpm: int = 0
    is_error: bool = False


AnyInput = Union[FunscriptAxisInput, RestimInput, CalculatedInput, As5311Input, ArithmeticInput, TasmotaInput, HeartRateInput]


PLAYER_DEFAULT_PORTS: dict[str, int] = {
    "heresphere": 23554,
    "mpc_hc": 13579,
}


@dataclass
class PlayerConfig:
    type: str = "heresphere"
    host: str = "127.0.0.1"
    port: int = 23554
    poll_interval_ms: int = 150
    restim_autostart_enabled: bool = False
    restim_autostart_urls: list[str] = field(default_factory=list)


@dataclass
class ThresholdSwitchConfig:
    threshold: float = 50.0
    active_high: bool = True
    hysteresis: float = 0.0


@dataclass
class TasmotaOutputConfig:
    host: str = ""
    device_index: int = 1
    timeout_s: float = 3.0
    repeat_interval_s: int = 0


@dataclass
class MqttOutputConfig:
    broker_host: str = ""
    broker_port: int = 1883
    username: str = ""
    password: str = ""
    command_topic: str = ""
    payload_on: str = "ON"
    payload_off: str = "OFF"
    status_topic: str = ""
    qos: int = 0
    retain: bool = False


@dataclass
class WsOutputConfig:
    """Configuration for a WebSocket continuous-value output."""
    url: str = "ws://localhost:12346/sensors/pressure"
    field_name: str = "pressure"
    send_interval_s: float = 1.0
    min_output: float = 100000.0
    max_output: float = 110000.0


@dataclass
class OutputConfig:
    name: str = ""
    enabled: bool = True
    type: Literal["threshold_tasmota", "threshold_mqtt", "ws_value"] = "threshold_tasmota"
    input_name: str = ""
    on_pause: Literal["hold", "force_on", "force_off"] = "hold"
    on_disconnect: Literal["hold", "force_on", "force_off"] = "force_off"
    on_missing_input: Literal["hold", "force_on", "force_off"] = "force_off"
    threshold: ThresholdSwitchConfig = field(default_factory=ThresholdSwitchConfig)
    tasmota: TasmotaOutputConfig = field(default_factory=TasmotaOutputConfig)
    mqtt: MqttOutputConfig = field(default_factory=MqttOutputConfig)
    ws: WsOutputConfig = field(default_factory=WsOutputConfig)


@dataclass
class GatewayConfig:
    player: PlayerConfig = field(default_factory=PlayerConfig)
    funscript_search_paths: list[str] = field(default_factory=list)
    inputs: list = field(default_factory=list)  # list[AnyInput]
    outputs: list[OutputConfig] = field(default_factory=list)


class OutputInstance:
    """Pairs a SignalProcessor with a DeviceDriver for a single output channel."""

    def __init__(
        self,
        config: OutputConfig,
        processor: object,
        driver: object,
    ) -> None:
        self.config = config
        self.processor = processor
        self.driver = driver
        self.last_input_value: float = 0.0
        self.last_output_state: bool = False
        self.consecutive_errors: int = 0
        self.is_degraded: bool = False
