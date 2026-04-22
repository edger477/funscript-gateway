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
    CalculatedEntry,
    CalculatedInput,
    FunscriptAxisInput,
    GatewayConfig,
    MqttOutputConfig,
    OutputConfig,
    PlayerConfig,
    RestimCondition,
    RestimInput,
    TasmotaOutputConfig,
    ThresholdSwitchConfig,
)

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "funscript-gateway"
CONFIG_PATH = CONFIG_DIR / "config.toml"
LOG_PATH = CONFIG_DIR / "funscript_gateway.log"


# ---------------------------------------------------------------------------
# Input deserialisation
# ---------------------------------------------------------------------------

def _funscript_axis_input_from_dict(d: dict) -> FunscriptAxisInput:
    return FunscriptAxisInput(
        name=d.get("name", ""),
        enabled=bool(d.get("enabled", True)),
        default_value=float(d.get("default_value", 0.0)),
    )


def _restim_input_from_dict(d: dict) -> RestimInput:
    cond_d = d.get("condition", {})
    condition = RestimCondition(
        playing=cond_d.get("playing", "any"),
        volume_ui_enabled=bool(cond_d.get("volume_ui_enabled", False)),
        volume_ui_above=bool(cond_d.get("volume_ui_above", True)),
        volume_ui_threshold=float(cond_d.get("volume_ui_threshold", 0.5)),
        volume_device_enabled=bool(cond_d.get("volume_device_enabled", False)),
        volume_device_above=bool(cond_d.get("volume_device_above", True)),
        volume_device_threshold=float(cond_d.get("volume_device_threshold", 0.5)),
    )
    return RestimInput(
        name=d.get("name", ""),
        url=d.get("url", "http://localhost:12348/v1/status"),
        enabled=bool(d.get("enabled", True)),
        poll_interval_s=float(d.get("poll_interval_s", 2.0)),
        default_value=bool(d.get("default_value", False)),
        condition=condition,
    )


def _calculated_input_from_dict(d: dict) -> CalculatedInput:
    entries = [
        CalculatedEntry(
            input_name=e.get("input_name", ""),
            operator=e.get("operator", "and"),
        )
        for e in d.get("entries", [])
    ]
    return CalculatedInput(
        name=d.get("name", ""),
        enabled=bool(d.get("enabled", True)),
        entries=entries,
    )


def _input_from_dict(d: dict):
    input_type = d.get("type", "funscript_axis")
    if input_type == "restim":
        return _restim_input_from_dict(d)
    if input_type == "calculated":
        return _calculated_input_from_dict(d)
    return _funscript_axis_input_from_dict(d)


# ---------------------------------------------------------------------------
# Output deserialisation
# ---------------------------------------------------------------------------

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
    # Support old key names for backwards compatibility
    input_name = d.get("input_name", d.get("axis_name", ""))
    on_missing = d.get("on_missing_input", d.get("on_missing_axis", "force_off"))
    return OutputConfig(
        name=d.get("name", ""),
        enabled=bool(d.get("enabled", True)),
        type=d.get("type", "threshold_tasmota"),
        input_name=input_name,
        on_pause=d.get("on_pause", "hold"),
        on_disconnect=d.get("on_disconnect", "force_off"),
        on_missing_input=on_missing,
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

    # Load inputs (new format)
    inputs = [_input_from_dict(i) for i in data.get("inputs", [])]

    # Backwards compat: load old [[axes]] sections as FunscriptAxisInput
    for a in data.get("axes", []):
        inputs.append(FunscriptAxisInput(
            name=a.get("name", ""),
            enabled=bool(a.get("enabled", True)),
            default_value=0.0,
        ))

    outputs = [_output_from_dict(o) for o in data.get("outputs", [])]
    return GatewayConfig(
        player=player,
        funscript_search_paths=search_paths,
        inputs=inputs,
        outputs=outputs,
    )


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Input serialisation
# ---------------------------------------------------------------------------

def _input_to_dict(inp) -> dict:
    if isinstance(inp, FunscriptAxisInput):
        return {
            "type": "funscript_axis",
            "name": inp.name,
            "enabled": inp.enabled,
            "default_value": inp.default_value,
        }
    if isinstance(inp, RestimInput):
        return {
            "type": "restim",
            "name": inp.name,
            "url": inp.url,
            "enabled": inp.enabled,
            "poll_interval_s": inp.poll_interval_s,
            "default_value": inp.default_value,
            "condition": {
                "playing": inp.condition.playing,
                "volume_ui_enabled": inp.condition.volume_ui_enabled,
                "volume_ui_above": inp.condition.volume_ui_above,
                "volume_ui_threshold": inp.condition.volume_ui_threshold,
                "volume_device_enabled": inp.condition.volume_device_enabled,
                "volume_device_above": inp.condition.volume_device_above,
                "volume_device_threshold": inp.condition.volume_device_threshold,
            },
        }
    if isinstance(inp, CalculatedInput):
        return {
            "type": "calculated",
            "name": inp.name,
            "enabled": inp.enabled,
            "entries": [
                {"input_name": e.input_name, "operator": e.operator}
                for e in inp.entries
            ],
        }
    return {}


def _output_to_dict(output: OutputConfig) -> dict:
    return {
        "name": output.name,
        "enabled": output.enabled,
        "type": output.type,
        "input_name": output.input_name,
        "on_pause": output.on_pause,
        "on_disconnect": output.on_disconnect,
        "on_missing_input": output.on_missing_input,
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
        "inputs": [_input_to_dict(i) for i in config.inputs],
        "outputs": [_output_to_dict(o) for o in config.outputs],
    }


def save_config(config: GatewayConfig) -> None:
    """Atomically write config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = _config_to_dict(config)
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
