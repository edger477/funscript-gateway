"""Tests for config round-trip serialization/deserialization."""

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from funscript_gateway.models import (
    As5311Input,
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


def _make_full_config() -> GatewayConfig:
    """Build a GatewayConfig with non-default values to test round-trip."""
    player = PlayerConfig(
        type="mpc_hc",
        host="192.168.1.5",
        port=13579,
        poll_interval_ms=200,
    )
    inputs = [
        FunscriptAxisInput(name="vibration", enabled=True),
        FunscriptAxisInput(name="stroke", enabled=False),
    ]
    tasmota_output = OutputConfig(
        name="Bed Vibrator",
        enabled=True,
        type="threshold_tasmota",
        input_name="vibration",
        on_pause="force_off",
        on_disconnect="force_off",
        threshold=ThresholdSwitchConfig(threshold=40.0, active_high=True, hysteresis=5.0),
        tasmota=TasmotaOutputConfig(host="192.168.1.42", device_index=2, timeout_s=5.0),
    )
    mqtt_output = OutputConfig(
        name="Atmosphere Light",
        enabled=False,
        type="threshold_mqtt",
        input_name="stroke",
        on_pause="hold",
        on_disconnect="force_off",
        threshold=ThresholdSwitchConfig(threshold=60.0, active_high=False, hysteresis=2.0),
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
        inputs=inputs,
        outputs=[tasmota_output, mqtt_output],
    )


def _roundtrip(config: GatewayConfig) -> GatewayConfig:
    """Save config to a temp file and reload it, returning the reloaded config."""
    from funscript_gateway import config as config_module

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
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
        assert result.inputs == []
        assert result.outputs == []

    def test_player_config_round_trips(self):
        cfg = GatewayConfig()
        cfg.player = PlayerConfig(type="mpc_hc", host="10.0.0.1", port=9999, poll_interval_ms=300)
        result = _roundtrip(cfg)
        assert result.player.type == "mpc_hc"
        assert result.player.host == "10.0.0.1"
        assert result.player.port == 9999
        assert result.player.poll_interval_ms == 300

    def test_funscript_axis_round_trip(self):
        cfg = GatewayConfig()
        cfg.inputs = [
            FunscriptAxisInput(name="vibration", enabled=True, default_value=0.1),
            FunscriptAxisInput(name="stroke", enabled=False, default_value=0.0),
        ]
        result = _roundtrip(cfg)
        assert len(result.inputs) == 2
        v = result.inputs[0]
        assert isinstance(v, FunscriptAxisInput)
        assert v.name == "vibration"
        assert v.enabled is True
        assert v.default_value == pytest.approx(0.1)
        s = result.inputs[1]
        assert s.name == "stroke"
        assert s.enabled is False

    def test_restim_input_round_trip(self):
        cfg = GatewayConfig()
        cfg.inputs = [
            RestimInput(
                name="restim_playing",
                url="http://localhost:12348/v1/status",
                enabled=True,
                poll_interval_s=3.0,
                default_value=True,
                condition=RestimCondition(
                    playing="yes",
                    volume_ui_enabled=True,
                    volume_ui_above=False,
                    volume_ui_threshold=0.3,
                    volume_device_enabled=False,
                ),
            )
        ]
        result = _roundtrip(cfg)
        assert len(result.inputs) == 1
        r = result.inputs[0]
        assert isinstance(r, RestimInput)
        assert r.name == "restim_playing"
        assert r.poll_interval_s == pytest.approx(3.0)
        assert r.default_value is True
        assert r.condition.playing == "yes"
        assert r.condition.volume_ui_enabled is True
        assert r.condition.volume_ui_above is False
        assert r.condition.volume_ui_threshold == pytest.approx(0.3)
        assert r.condition.volume_device_enabled is False

    def test_calculated_input_round_trip(self):
        cfg = GatewayConfig()
        cfg.inputs = [
            FunscriptAxisInput(name="vibration"),
            RestimInput(name="restim"),
            CalculatedInput(
                name="combined",
                enabled=True,
                entries=[
                    CalculatedEntry(input_name="vibration", operator="and", above=True, threshold=60.0),
                    CalculatedEntry(input_name="restim", operator="or", above=False, threshold=30.0),
                ],
            ),
        ]
        result = _roundtrip(cfg)
        calc = result.inputs[2]
        assert isinstance(calc, CalculatedInput)
        assert calc.name == "combined"
        assert len(calc.entries) == 2
        assert calc.entries[0].input_name == "vibration"
        assert calc.entries[0].above is True
        assert calc.entries[0].threshold == pytest.approx(60.0)
        assert calc.entries[1].input_name == "restim"
        assert calc.entries[1].operator == "or"
        assert calc.entries[1].above is False
        assert calc.entries[1].threshold == pytest.approx(30.0)

    def test_as5311_input_round_trip(self):
        cfg = GatewayConfig()
        cfg.inputs = [
            As5311Input(
                name="stroke_pos",
                url="ws://localhost:12346/sensors/as5311",
                enabled=True,
                threshold_mm=0.5,
                range_mm=1.5,
            )
        ]
        result = _roundtrip(cfg)
        assert len(result.inputs) == 1
        a = result.inputs[0]
        assert isinstance(a, As5311Input)
        assert a.name == "stroke_pos"
        assert a.url == "ws://localhost:12346/sensors/as5311"
        assert a.threshold_mm == pytest.approx(0.5)
        assert a.range_mm == pytest.approx(1.5)

    def test_tasmota_output_round_trips(self):
        cfg = GatewayConfig()
        cfg.outputs = [
            OutputConfig(
                name="Test Output",
                enabled=True,
                type="threshold_tasmota",
                input_name="vibration",
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
        assert o.input_name == "vibration"
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
                input_name="stroke",
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
        assert o.input_name == "stroke"
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
        assert len(result.inputs) == 2
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
                mock.patch.object(config_module, "CONFIG_PATH", tmp_path / "config.toml"),
            ):
                result = config_module.load_config()
        assert result.player.type == "heresphere"
        assert result.outputs == []

    def test_save_is_atomic(self):
        from funscript_gateway import config as config_module

        cfg = _make_full_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with (
                mock.patch.object(config_module, "CONFIG_DIR", tmp_path),
                mock.patch.object(config_module, "CONFIG_PATH", tmp_path / "config.toml"),
            ):
                config_module.save_config(cfg)
                config_path = tmp_path / "config.toml"
                assert config_path.exists()
                assert config_path.stat().st_size > 0
                remaining = list(tmp_path.glob("*.tmp"))
                assert remaining == []

    def test_search_paths_round_trip(self):
        cfg = GatewayConfig()
        cfg.funscript_search_paths = ["C:/Scripts", "D:/funscripts"]
        result = _roundtrip(cfg)
        assert result.funscript_search_paths == ["C:/Scripts", "D:/funscripts"]

    def test_backwards_compat_axis_name_key(self):
        """Old config files using axis_name are transparently upgraded on load."""
        from funscript_gateway import config as config_module
        import tomli_w

        old_toml = {
            "outputs": [
                {
                    "name": "old_output",
                    "enabled": True,
                    "type": "threshold_tasmota",
                    "axis_name": "vibration",
                    "on_pause": "hold",
                    "on_disconnect": "force_off",
                    "on_missing_axis": "force_off",
                    "threshold": {"threshold": 50.0, "active_high": True, "hysteresis": 0.0},
                    "tasmota": {"host": "1.2.3.4", "device_index": 1, "timeout_s": 3.0, "repeat_interval_s": 0},
                    "mqtt": {
                        "broker_host": "", "broker_port": 1883, "username": "", "password": "",
                        "command_topic": "", "payload_on": "ON", "payload_off": "OFF",
                        "status_topic": "", "qos": 0, "retain": False,
                    },
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "config.toml"
            with open(config_path, "wb") as fh:
                tomli_w.dump(old_toml, fh)
            with (
                mock.patch.object(config_module, "CONFIG_DIR", tmp_path),
                mock.patch.object(config_module, "CONFIG_PATH", config_path),
            ):
                result = config_module.load_config()

        assert len(result.outputs) == 1
        assert result.outputs[0].input_name == "vibration"
        assert result.outputs[0].on_missing_input == "force_off"
