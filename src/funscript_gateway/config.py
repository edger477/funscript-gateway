"""Configuration persistence for funscript-gateway.

Reads/writes TOML at %APPDATA%\\funscript-gateway\\config.toml.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]
from pathlib import Path

import tomli_w

from funscript_gateway.models import (
    FunscriptAxis,
    GatewayConfig,
    MqttOutputConfig,
    OutputConfig,
    PlayerConfig,
    TasmotaOutputConfig,
    ThresholdSwitchConfig,
)

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "funscript-gateway"
CONFIG_PATH = CONFIG_DIR / "config.toml"
LOG_PATH = CONFIG_DIR / "funscript_gateway.log"


def _axis_from_dict(d: dict) -> FunscriptAxis:
    return FunscriptAxis(
        name=d.get("name", ""),
        file_path=d.get("file_path", ""),
        enabled=d.get("enabled", True),
    )


def _output_from_dict(d: dict) -> OutputConfig:
    threshold_d = d.get("threshold", {})
    tasmota_d = d.get("tasmota", {})
    mqtt_d = d.get("mqtt", {})

    threshold = ThresholdSwitchConfig(
        threshold=float(threshold_d.get("threshold", 50.0)),
        active_high=bool(threshold_d.get("active_high", True)),
        hysteresis=float(threshold_d.get("hysteresis", 0.0)),
    )
    tasmota = TasmotaOutputConfig(
        host=tasmota_d.get("host", ""),
        device_index=int(tasmota_d.get("device_index", 1)),
        timeout_s=float(tasmota_d.get("timeout_s", 3.0)),
        repeat_interval_s=int(tasmota_d.get("repeat_interval_s", 0)),
    )
    mqtt = MqttOutputConfig(
        broker_host=mqtt_d.get("broker_host", ""),
        broker_port=int(mqtt_d.get("broker_port", 1883)),
        username=mqtt_d.get("username", ""),
        password=mqtt_d.get("password", ""),
        command_topic=mqtt_d.get("command_topic", ""),
        payload_on=mqtt_d.get("payload_on", "ON"),
        payload_off=mqtt_d.get("payload_off", "OFF"),
        status_topic=mqtt_d.get("status_topic", ""),
        qos=int(mqtt_d.get("qos", 0)),
        retain=bool(mqtt_d.get("retain", False)),
    )
    return OutputConfig(
        name=d.get("name", ""),
        enabled=bool(d.get("enabled", True)),
        type=d.get("type", "threshold_tasmota"),
        axis_name=d.get("axis_name", ""),
        on_pause=d.get("on_pause", "hold"),
        on_disconnect=d.get("on_disconnect", "force_off"),
        on_missing_axis=d.get("on_missing_axis", "force_off"),
        threshold=threshold,
        tasmota=tasmota,
        mqtt=mqtt,
    )


def _config_from_dict(data: dict) -> GatewayConfig:
    player_d = data.get("player", {})
    player = PlayerConfig(
        type=player_d.get("type", "heresphere"),
        host=player_d.get("host", "127.0.0.1"),
        port=int(player_d.get("port", 23554)),
        poll_interval_ms=int(player_d.get("poll_interval_ms", 150)),
    )
    funscript_d = data.get("funscript", {})
    search_paths = [str(p) for p in funscript_d.get("search_paths", [])]
    axes = [_axis_from_dict(a) for a in data.get("axes", [])]
    outputs = [_output_from_dict(o) for o in data.get("outputs", [])]
    return GatewayConfig(
        player=player,
        funscript_search_paths=search_paths,
        axes=axes,
        outputs=outputs,
    )


def load_config() -> GatewayConfig:
    """Read config.toml and return a GatewayConfig.

    Returns a default config if the file is missing.
    Backs up the file as config.toml.bak on parse error and returns defaults.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        logger.info("No config file found at %s; using defaults.", CONFIG_PATH)
        return GatewayConfig()
    try:
        with CONFIG_PATH.open("rb") as fh:
            data = tomllib.load(fh)
        return _config_from_dict(data)
    except Exception as exc:  # noqa: BLE001
        bak = CONFIG_PATH.with_suffix(".toml.bak")
        logger.error(
            "Failed to parse %s (%s); backing up to %s and using defaults.",
            CONFIG_PATH,
            exc,
            bak,
        )
        try:
            shutil.copy2(CONFIG_PATH, bak)
        except OSError:
            pass
        return GatewayConfig()


def _axis_to_dict(axis: FunscriptAxis) -> dict:
    return {
        "name": axis.name,
        "file_path": axis.file_path,
        "enabled": axis.enabled,
    }


def _output_to_dict(output: OutputConfig) -> dict:
    d: dict = {
        "name": output.name,
        "enabled": output.enabled,
        "type": output.type,
        "axis_name": output.axis_name,
        "on_pause": output.on_pause,
        "on_disconnect": output.on_disconnect,
        "on_missing_axis": output.on_missing_axis,
        "threshold": {
            "threshold": output.threshold.threshold,
            "active_high": output.threshold.active_high,
            "hysteresis": output.threshold.hysteresis,
        },
        "tasmota": {
            "host": output.tasmota.host,
            "device_index": output.tasmota.device_index,
            "timeout_s": output.tasmota.timeout_s,
            "repeat_interval_s": output.tasmota.repeat_interval_s,
        },
        "mqtt": {
            "broker_host": output.mqtt.broker_host,
            "broker_port": output.mqtt.broker_port,
            "username": output.mqtt.username,
            "password": output.mqtt.password,
            "command_topic": output.mqtt.command_topic,
            "payload_on": output.mqtt.payload_on,
            "payload_off": output.mqtt.payload_off,
            "status_topic": output.mqtt.status_topic,
            "qos": output.mqtt.qos,
            "retain": output.mqtt.retain,
        },
    }
    return d


def _config_to_dict(config: GatewayConfig) -> dict:
    return {
        "player": {
            "type": config.player.type,
            "host": config.player.host,
            "port": config.player.port,
            "poll_interval_ms": config.player.poll_interval_ms,
        },
        "funscript": {
            "search_paths": list(config.funscript_search_paths),
        },
        "axes": [_axis_to_dict(a) for a in config.axes],
        "outputs": [_output_to_dict(o) for o in config.outputs],
    }


def save_config(config: GatewayConfig) -> None:
    """Atomically write config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = _config_to_dict(config)
    # Write to a temp file in the same directory, then rename atomically.
    fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            tomli_w.dump(data, fh)
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    logger.debug("Configuration saved to %s.", CONFIG_PATH)
