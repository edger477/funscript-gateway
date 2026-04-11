"""All dataclasses and enums for funscript-gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Literal

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
class FunscriptAxis:
    name: str
    file_path: str
    enabled: bool = True
    actions: list[tuple[int, int]] = field(default_factory=list)
    current_value: float = 0.0
    file_missing: bool = False


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
    axis_name: str = ""
    on_pause: Literal["hold", "force_on", "force_off"] = "hold"
    on_disconnect: Literal["hold", "force_on", "force_off"] = "force_off"
    on_missing_axis: Literal["hold", "force_on", "force_off"] = "force_off"
    threshold: ThresholdSwitchConfig = field(default_factory=ThresholdSwitchConfig)
    tasmota: TasmotaOutputConfig = field(default_factory=TasmotaOutputConfig)
    mqtt: MqttOutputConfig = field(default_factory=MqttOutputConfig)


@dataclass
class GatewayConfig:
    player: PlayerConfig = field(default_factory=PlayerConfig)
    funscript_search_paths: list[str] = field(default_factory=list)
    axes: list[FunscriptAxis] = field(default_factory=list)
    outputs: list[OutputConfig] = field(default_factory=list)


class OutputInstance:
    """Pairs a SignalProcessor with a DeviceDriver for a single output channel.

    Not a dataclass because it holds live processor and driver objects that
    cannot be default-constructed.
    """

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
