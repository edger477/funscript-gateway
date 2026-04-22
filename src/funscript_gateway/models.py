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


@dataclass
class CalculatedInput:
    name: str
    enabled: bool = True
    entries: list[CalculatedEntry] = field(default_factory=list)
    # Runtime:
    current_value: float = 0.0


AnyInput = Union[FunscriptAxisInput, RestimInput, CalculatedInput]


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
class OutputConfig:
    name: str = ""
    enabled: bool = True
    type: Literal["threshold_tasmota", "threshold_mqtt"] = "threshold_tasmota"
    input_name: str = ""
    on_pause: Literal["hold", "force_on", "force_off"] = "hold"
    on_disconnect: Literal["hold", "force_on", "force_off"] = "force_off"
    on_missing_input: Literal["hold", "force_on", "force_off"] = "force_off"
    threshold: ThresholdSwitchConfig = field(default_factory=ThresholdSwitchConfig)
    tasmota: TasmotaOutputConfig = field(default_factory=TasmotaOutputConfig)
    mqtt: MqttOutputConfig = field(default_factory=MqttOutputConfig)


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
