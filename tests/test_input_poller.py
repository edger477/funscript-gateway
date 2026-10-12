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


class TestCalculatedHysteresis:
    @staticmethod
    def _calc(**entry_kwargs):
        from funscript_gateway.models import CalculatedEntry, CalculatedInput

        return CalculatedInput(
            name="c", entries=[CalculatedEntry(input_name="x", **entry_kwargs)]
        )

    def test_switches_on_at_threshold_and_holds_until_below_off(self):
        from funscript_gateway.outputs.input_poller import _eval_calculated

        calc = self._calc(threshold=60.0, off_threshold=40.0)
        seq = [(50, 0), (60, 100), (50, 100), (40, 100), (39.9, 0), (50, 0), (61, 100)]
        for value, expected in seq:
            assert _eval_calculated(calc, {"x": value}) == expected, value

    def test_without_off_threshold_behaves_as_plain_compare(self):
        from funscript_gateway.outputs.input_poller import _eval_calculated

        calc = self._calc(threshold=60.0)
        assert [_eval_calculated(calc, {"x": v}) for v in (61, 50, 61)] == [100, 0, 100]

    def test_off_above_on_degrades_to_plain_compare(self):
        from funscript_gateway.outputs.input_poller import _eval_calculated

        calc = self._calc(threshold=40.0, off_threshold=60.0)
        assert [_eval_calculated(calc, {"x": v}) for v in (50, 39, 45)] == [100, 0, 100]

    def test_inverse_applies_before_hysteresis(self):
        from funscript_gateway.outputs.input_poller import _eval_calculated

        calc = self._calc(threshold=60.0, off_threshold=40.0, inverse=True)
        # effective = 100 - x
        assert [_eval_calculated(calc, {"x": v}) for v in (30, 55, 61)] == [100, 100, 0]

    def test_later_entries_update_state_even_when_result_is_decided(self):
        from funscript_gateway.models import CalculatedEntry, CalculatedInput
        from funscript_gateway.outputs.input_poller import _eval_calculated

        hyst = CalculatedEntry(input_name="h", operator="and", threshold=60.0, off_threshold=40.0)
        calc = CalculatedInput(name="c", entries=[CalculatedEntry(input_name="gate"), hyst])
        _eval_calculated(calc, {"gate": 0, "h": 70})  # gate false, but h crosses on
        assert hyst.state is True
        assert _eval_calculated(calc, {"gate": 100, "h": 50}) == 100  # h held ON
