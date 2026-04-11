"""Tests for config round-trip serialization/deserialization."""

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from funscript_gateway.models import (
    FunscriptAxis,
    GatewayConfig,
    MqttOutputConfig,
    OutputConfig,
    PlayerConfig,
    TasmotaOutputConfig,
    ThresholdSwitchConfig,
)


def _make_full_config() -> GatewayConfig:
    """Build a GatewayConfig with non-default values to test round-trip."""
    player = PlayerConfig(
        type="mpc_hc",
        host="192.168.1.5",
        port=13579,
        poll_interval_ms=200,
    )
    axes = [
        FunscriptAxis(
            name="vibration",
            file_path="C:/Videos/example.vibration.funscript",
            enabled=True,
        ),
        FunscriptAxis(
            name="stroke",
            file_path="C:/Videos/example.stroke.funscript",
            enabled=False,
        ),
    ]
    tasmota_output = OutputConfig(
        name="Bed Vibrator",
        enabled=True,
        type="threshold_tasmota",
        axis_name="vibration",
        on_pause="force_off",
        on_disconnect="force_off",
        threshold=ThresholdSwitchConfig(
            threshold=40.0,
            active_high=True,
            hysteresis=5.0,
        ),
        tasmota=TasmotaOutputConfig(
            host="192.168.1.42",
            device_index=2,
            timeout_s=5.0,
        ),
    )
    mqtt_output = OutputConfig(
        name="Atmosphere Light",
        enabled=False,
        type="threshold_mqtt",
        axis_name="stroke",
        on_pause="hold",
        on_disconnect="force_off",
        threshold=ThresholdSwitchConfig(
            threshold=60.0,
            active_high=False,
            hysteresis=2.0,
        ),
        mqtt=MqttOutputConfig(
            broker_host="192.168.1.10",
            broker_port=1884,
            command_topic="home/light/set",
            payload_on="1",
            payload_off="0",
            status_topic="home/light/state",
            qos=1,
            retain=True,
        ),
    )
    return GatewayConfig(
        player=player,
        funscript_search_paths=["/extra/scripts", "D:/funscripts"],
        axes=axes,
        outputs=[tasmota_output, mqtt_output],
    )


def _roundtrip(config: GatewayConfig) -> GatewayConfig:
    """Save config to a temp file and reload it, returning the reloaded config."""
    from funscript_gateway import config as config_module

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Patch the module-level paths.
        with (
            mock.patch.object(config_module, "CONFIG_DIR", tmp_path),
            mock.patch.object(config_module, "CONFIG_PATH", tmp_path / "config.toml"),
        ):
            config_module.save_config(config)
            return config_module.load_config()


class TestConfigRoundTrip:
    def test_default_config_round_trips(self):
        result = _roundtrip(GatewayConfig())
        assert result.player.type == "heresphere"
        assert result.player.host == "127.0.0.1"
        assert result.player.port == 23554
        assert result.player.poll_interval_ms == 150
        assert result.funscript_search_paths == []
        assert result.axes == []
        assert result.outputs == []

    def test_player_config_round_trips(self):
        cfg = GatewayConfig()
        cfg.player = PlayerConfig(type="mpc_hc", host="10.0.0.1", port=9999, poll_interval_ms=300)
        result = _roundtrip(cfg)
        assert result.player.type == "mpc_hc"
        assert result.player.host == "10.0.0.1"
        assert result.player.port == 9999
        assert result.player.poll_interval_ms == 300

    def test_axes_round_trip(self):
        cfg = GatewayConfig()
        cfg.axes = [
            FunscriptAxis(name="vibration", file_path="/test.vibration.funscript", enabled=True),
            FunscriptAxis(name="stroke", file_path="/test.stroke.funscript", enabled=False),
        ]
        result = _roundtrip(cfg)
        assert len(result.axes) == 2
        assert result.axes[0].name == "vibration"
        assert result.axes[0].file_path == "/test.vibration.funscript"
        assert result.axes[0].enabled is True
        assert result.axes[1].name == "stroke"
        assert result.axes[1].enabled is False

    def test_tasmota_output_round_trips(self):
        cfg = GatewayConfig()
        cfg.outputs = [
            OutputConfig(
                name="Test Output",
                enabled=True,
                type="threshold_tasmota",
                axis_name="vibration",
                on_pause="force_off",
                on_disconnect="force_off",
                threshold=ThresholdSwitchConfig(threshold=40.0, active_high=True, hysteresis=5.0),
                tasmota=TasmotaOutputConfig(host="192.168.1.42", device_index=2, timeout_s=5.0),
            )
        ]
        result = _roundtrip(cfg)
        assert len(result.outputs) == 1
        o = result.outputs[0]
        assert o.name == "Test Output"
        assert o.enabled is True
        assert o.type == "threshold_tasmota"
        assert o.axis_name == "vibration"
        assert o.on_pause == "force_off"
        assert o.on_disconnect == "force_off"
        assert o.threshold.threshold == pytest.approx(40.0)
        assert o.threshold.active_high is True
        assert o.threshold.hysteresis == pytest.approx(5.0)
        assert o.tasmota.host == "192.168.1.42"
        assert o.tasmota.device_index == 2
        assert o.tasmota.timeout_s == pytest.approx(5.0)

    def test_mqtt_output_round_trips(self):
        cfg = GatewayConfig()
        cfg.outputs = [
            OutputConfig(
                name="Light",
                enabled=False,
                type="threshold_mqtt",
                axis_name="stroke",
                on_pause="hold",
                on_disconnect="force_on",
                threshold=ThresholdSwitchConfig(threshold=60.0, active_high=False, hysteresis=2.0),
                mqtt=MqttOutputConfig(
                    broker_host="broker.local",
                    broker_port=1884,
                    command_topic="home/light/set",
                    payload_on="1",
                    payload_off="0",
                    status_topic="home/light/state",
                    qos=2,
                    retain=True,
                ),
            )
        ]
        result = _roundtrip(cfg)
        o = result.outputs[0]
        assert o.enabled is False
        assert o.type == "threshold_mqtt"
        assert o.on_disconnect == "force_on"
        assert o.threshold.active_high is False
        assert o.mqtt.broker_host == "broker.local"
        assert o.mqtt.broker_port == 1884
        assert o.mqtt.command_topic == "home/light/set"
        assert o.mqtt.payload_on == "1"
        assert o.mqtt.payload_off == "0"
        assert o.mqtt.status_topic == "home/light/state"
        assert o.mqtt.qos == 2
        assert o.mqtt.retain is True

    def test_full_config_round_trips(self):
        cfg = _make_full_config()
        result = _roundtrip(cfg)

        assert result.player.type == "mpc_hc"
        assert result.player.host == "192.168.1.5"
        assert result.funscript_search_paths == ["/extra/scripts", "D:/funscripts"]
        assert len(result.axes) == 2
        assert len(result.outputs) == 2

        tasmota_out = result.outputs[0]
        assert tasmota_out.name == "Bed Vibrator"
        assert tasmota_out.tasmota.device_index == 2

        mqtt_out = result.outputs[1]
        assert mqtt_out.name == "Atmosphere Light"
        assert mqtt_out.mqtt.retain is True

    def test_load_missing_file_returns_defaults(self):
        from funscript_gateway import config as config_module

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "nonexistent"
            with (
                mock.patch.object(config_module, "CONFIG_DIR", tmp_path),
                mock.patch.object(
                    config_module, "CONFIG_PATH", tmp_path / "config.toml"
                ),
            ):
                result = config_module.load_config()
        assert result.player.type == "heresphere"
        assert result.outputs == []

    def test_save_is_atomic(self):
        """Verify the file is written completely (not partially)."""
        from funscript_gateway import config as config_module

        cfg = _make_full_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with (
                mock.patch.object(config_module, "CONFIG_DIR", tmp_path),
                mock.patch.object(config_module, "CONFIG_PATH", tmp_path / "config.toml"),
            ):
                config_module.save_config(cfg)
                # The config file must exist and have non-zero size.
                config_path = tmp_path / "config.toml"
                assert config_path.exists()
                assert config_path.stat().st_size > 0
                # No temp files left over.
                remaining = list(tmp_path.glob("*.tmp"))
                assert remaining == []

    def test_search_paths_round_trip(self):
        cfg = GatewayConfig()
        cfg.funscript_search_paths = ["C:/Scripts", "D:/funscripts"]
        result = _roundtrip(cfg)
        assert result.funscript_search_paths == ["C:/Scripts", "D:/funscripts"]
