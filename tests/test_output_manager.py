"""Tests for OutputManager: non-blocking sends, failure backoff, index alignment."""

import asyncio

import pytest

from funscript_gateway.app_state import AppState
from funscript_gateway.funscript.engine import FunscriptEngine
from funscript_gateway.models import (
    CalculatedInput,
    MediaConnectionState,
    OutputConfig,
    OutputInstance,
    PlayerState,
)
from funscript_gateway.outputs import manager as manager_module
from funscript_gateway.outputs.manager import OutputManager
from funscript_gateway.outputs.threshold import ThresholdSwitchProcessor


class SlowDriver:
    """Driver whose sends take `delay` seconds; optionally always fails."""

    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.calls: list[bool] = []

    async def set_state(self, on: bool) -> None:
        self.calls.append(on)
        await asyncio.sleep(self.delay)
        if self.fail:
            raise OSError("Name or service not known")


def _playing_state() -> PlayerState:
    return PlayerState(
        connection_state=MediaConnectionState.CONNECTED_AND_PLAYING,
        file_path="/v.mp4",
        current_time_ms=0,
    )


def _setup(*drivers) -> tuple[AppState, OutputManager]:
    app_state = AppState()
    app_state.player_state = _playing_state()
    inp = CalculatedInput(name="in", entries=[])
    inp.current_value = 100.0
    app_state.inputs = [inp]
    outputs = []
    for i, driver in enumerate(drivers):
        cfg = OutputConfig(name=f"out{i}", input_name="in")
        outputs.append(
            OutputInstance(cfg, ThresholdSwitchProcessor(cfg.threshold), driver)
        )
    app_state.outputs = outputs
    return app_state, OutputManager(app_state, FunscriptEngine(app_state))


class TestNonBlockingSends:
    @pytest.mark.asyncio
    async def test_slow_driver_does_not_block_evaluation(self):
        slow = SlowDriver(delay=5.0)
        fast = SlowDriver()
        app_state, mgr = _setup(slow, fast)
        mgr._was_playing = True  # skip autostart

        loop = asyncio.get_event_loop()
        t0 = loop.time()
        mgr._evaluate_once()
        assert loop.time() - t0 < 0.1

        await asyncio.sleep(0.01)
        assert fast.calls == [True]
        assert slow.calls == [True]  # started, still in flight
        assert app_state.outputs[0].send_task is not None
        app_state.outputs[0].send_task.cancel()

    @pytest.mark.asyncio
    async def test_inflight_send_delivers_latest_state(self):
        driver = SlowDriver(delay=0.05)
        app_state, mgr = _setup(driver)
        out = app_state.outputs[0]

        mgr._dispatch(out, True)
        await asyncio.sleep(0)  # let the first send start
        mgr._dispatch(out, False)  # while the first send is in flight
        mgr._dispatch(out, True)
        mgr._dispatch(out, False)
        await out.send_task

        # The first send ran; then only the latest pending state was sent.
        assert driver.calls == [True, False]


class TestFailureBackoff:
    @pytest.mark.asyncio
    async def test_failure_backs_off_instead_of_retrying_every_tick(self):
        driver = SlowDriver(fail=True)
        app_state, mgr = _setup(driver)
        out = app_state.outputs[0]

        mgr._dispatch(out, True)
        await out.send_task
        assert out.consecutive_errors == 1
        assert out.retry_at > asyncio.get_event_loop().time()

        for _ in range(10):
            mgr._dispatch(out, True)
        assert driver.calls == [True]  # no retries during backoff

    @pytest.mark.asyncio
    async def test_backoff_grows_and_is_capped(self):
        driver = SlowDriver(fail=True)
        app_state, mgr = _setup(driver)
        out = app_state.outputs[0]
        loop = asyncio.get_event_loop()

        delays = []
        for _ in range(12):
            out.retry_at = 0.0
            mgr._dispatch(out, True)
            await out.send_task
            delays.append(out.retry_at - loop.time())

        assert delays[1] > delays[0]
        assert max(delays) <= manager_module._RETRY_BACKOFF_MAX_S + 0.01
        assert out.is_degraded

    @pytest.mark.asyncio
    async def test_success_clears_error_state(self):
        driver = SlowDriver(fail=True)
        app_state, mgr = _setup(driver)
        out = app_state.outputs[0]
        mgr._dispatch(out, True)
        await out.send_task

        driver.fail = False
        out.retry_at = 0.0
        mgr._dispatch(out, True)
        await out.send_task
        assert out.consecutive_errors == 0
        assert out.retry_at == 0.0


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_skips_known_unreachable_outputs(self):
        bad = SlowDriver(delay=5.0)
        good = SlowDriver()
        app_state, mgr = _setup(bad, good)
        app_state.outputs[0].consecutive_errors = 2

        await asyncio.wait_for(mgr._send_disconnect_states(), timeout=1.0)
        assert bad.calls == []
        assert good.calls == [False]


class TestIndexAlignment:
    @pytest.mark.asyncio
    async def test_failed_driver_keeps_slot(self, monkeypatch):
        app_state = AppState()
        app_state.config.outputs = [
            OutputConfig(name="a"),
            OutputConfig(name="broken", type="threshold_mqtt"),
            OutputConfig(name="c"),
        ]
        mgr = OutputManager(app_state, FunscriptEngine(app_state))

        async def fake_create_driver(cfg):
            return None if cfg.name == "broken" else SlowDriver()

        monkeypatch.setattr(mgr, "_create_driver", fake_create_driver)
        await mgr._setup_outputs()

        assert [o.config.name for o in app_state.outputs] == ["a", "broken", "c"]
        assert app_state.outputs[1].driver is None
