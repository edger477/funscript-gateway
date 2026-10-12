"""Tests for InputPoller: independent HTTP polls and HR packet parsing."""

import asyncio
import time

import pytest

from funscript_gateway.app_state import AppState
from funscript_gateway.models import TasmotaInput
from funscript_gateway.outputs import input_poller as poller_module
from funscript_gateway.outputs.input_poller import InputPoller, _parse_hr_measurement


class TestParallelPolls:
    @pytest.mark.asyncio
    async def test_slow_endpoint_does_not_block_tick_or_other_inputs(self, monkeypatch):
        def fake_fetch(url, timeout=3.0):
            if "slow" in url:
                time.sleep(0.5)  # e.g. an unresolvable host name
            return {"POWER1": "ON"}

        monkeypatch.setattr(poller_module, "_fetch_json", fake_fetch)

        app_state = AppState()
        slow = TasmotaInput(name="slow", host="slow")
        fast = TasmotaInput(name="fast", host="fast")
        app_state.inputs = [slow, fast]
        poller = InputPoller(app_state)

        loop = asyncio.get_event_loop()
        t0 = loop.time()
        poller._tick(loop.time())
        assert loop.time() - t0 < 0.05  # tick only schedules polls

        await asyncio.sleep(0.1)
        assert fast.current_value == 100.0
        assert slow.current_value == 0.0  # still in flight

        # A second tick must not start a duplicate poll for the in-flight input.
        poller._tick(loop.time() + 100)
        assert len(poller._poll_tasks) == 2
        await asyncio.gather(*poller._poll_tasks.values())
        assert slow.current_value == 100.0

    @pytest.mark.asyncio
    async def test_disabled_input_poll_is_cancelled(self, monkeypatch):
        monkeypatch.setattr(poller_module, "_fetch_json", lambda url, timeout=3.0: {})
        app_state = AppState()
        inp = TasmotaInput(name="t", host="h")
        app_state.inputs = [inp]
        poller = InputPoller(app_state)
        loop = asyncio.get_event_loop()

        poller._tick(loop.time())
        assert "t" in poller._poll_tasks
        inp.enabled = False
        poller._tick(loop.time())
        assert poller._poll_tasks == {}
        assert poller._last_poll == {}


class TestHrParsing:
    def test_8bit(self):
        assert _parse_hr_measurement(bytes([0x00, 72])) == 72

    def test_16bit(self):
        assert _parse_hr_measurement(bytes([0x01, 0x2C, 0x01])) == 300

    @pytest.mark.parametrize("data", [b"", b"\x00", b"\x01\x2c"])
    def test_short_packets_return_none(self, data):
        assert _parse_hr_measurement(data) is None
