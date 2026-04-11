"""Tests for ThresholdSwitchProcessor."""

import pytest

from funscript_gateway.models import ThresholdSwitchConfig
from funscript_gateway.outputs.threshold import ThresholdSwitchProcessor


def make_processor(
    threshold: float = 50.0,
    active_high: bool = True,
    hysteresis: float = 0.0,
) -> ThresholdSwitchProcessor:
    cfg = ThresholdSwitchConfig(
        threshold=threshold,
        active_high=active_high,
        hysteresis=hysteresis,
    )
    return ThresholdSwitchProcessor(cfg)


class TestThresholdBasic:
    def test_starts_off(self):
        p = make_processor(threshold=50.0)
        # Initial state is OFF; below threshold stays OFF
        assert p.process(30.0) is False

    def test_turns_on_at_threshold(self):
        p = make_processor(threshold=50.0)
        assert p.process(50.0) is True

    def test_turns_on_above_threshold(self):
        p = make_processor(threshold=50.0)
        assert p.process(75.0) is True

    def test_stays_on_at_threshold(self):
        p = make_processor(threshold=50.0)
        p.process(75.0)  # turn on
        assert p.process(50.0) is True

    def test_turns_off_below_threshold(self):
        p = make_processor(threshold=50.0)
        p.process(75.0)   # turn on
        assert p.process(49.9) is False

    def test_zero_threshold_always_on(self):
        p = make_processor(threshold=0.0)
        assert p.process(0.0) is True
        assert p.process(100.0) is True

    def test_max_threshold_never_on(self):
        # threshold=100 with no hysteresis: value must be >= 100 to turn on
        p = make_processor(threshold=100.0)
        assert p.process(99.9) is False
        assert p.process(100.0) is True


class TestThresholdHysteresis:
    def test_hysteresis_dead_band_holds_off_state(self):
        # threshold=50, hysteresis=10 → upper=55, lower=45
        p = make_processor(threshold=50.0, hysteresis=10.0)
        # Value 52 is inside dead band → stays OFF
        assert p.process(52.0) is False

    def test_hysteresis_turns_on_at_upper_edge(self):
        p = make_processor(threshold=50.0, hysteresis=10.0)
        assert p.process(55.0) is True

    def test_hysteresis_stays_on_inside_dead_band(self):
        p = make_processor(threshold=50.0, hysteresis=10.0)
        p.process(60.0)  # turn on
        # Value inside dead band [45, 55] → stays ON
        assert p.process(50.0) is True
        assert p.process(45.0) is True

    def test_hysteresis_turns_off_below_lower_edge(self):
        p = make_processor(threshold=50.0, hysteresis=10.0)
        p.process(60.0)  # turn on
        assert p.process(44.9) is False

    def test_hysteresis_prevents_rapid_toggling(self):
        p = make_processor(threshold=50.0, hysteresis=10.0)
        # Oscillate between 48 and 52 (inside dead band after initial OFF)
        states = [p.process(v) for v in [48, 52, 48, 52, 48]]
        assert all(s is False for s in states)

    def test_hysteresis_zero_behaves_like_no_hysteresis(self):
        p = make_processor(threshold=50.0, hysteresis=0.0)
        assert p.process(49.9) is False
        assert p.process(50.0) is True
        assert p.process(49.9) is False


class TestActiveHighFalse:
    def test_active_low_inverts_output(self):
        p = make_processor(threshold=50.0, active_high=False)
        # Below threshold → output is True (inverted)
        assert p.process(30.0) is True

    def test_active_low_at_threshold_is_false(self):
        p = make_processor(threshold=50.0, active_high=False)
        # At or above threshold → internal state becomes True → inverted = False
        assert p.process(50.0) is False

    def test_active_low_above_threshold_is_false(self):
        p = make_processor(threshold=50.0, active_high=False)
        assert p.process(80.0) is False

    def test_active_low_hysteresis_combo(self):
        # threshold=50, hysteresis=10, active_high=False
        # upper=55, lower=45
        p = make_processor(threshold=50.0, hysteresis=10.0, active_high=False)
        # Below threshold, starts OFF internally → active_low=True
        assert p.process(30.0) is True
        # Reach upper edge → internal ON → active_low=False
        assert p.process(55.0) is False
        # Drop back into dead band → stays False
        assert p.process(50.0) is False
        # Drop below lower edge → internal OFF → active_low=True
        assert p.process(44.9) is True


class TestThresholdEdgeCases:
    def test_value_exactly_at_lower_edge_stays_on(self):
        # lower_edge = 50 - 5 = 45; value=45 should NOT turn off (requires < 45)
        p = make_processor(threshold=50.0, hysteresis=10.0)
        p.process(60.0)  # turn on
        assert p.process(45.0) is True

    def test_value_just_below_lower_edge_turns_off(self):
        p = make_processor(threshold=50.0, hysteresis=10.0)
        p.process(60.0)
        assert p.process(44.999) is False

    def test_state_persists_across_multiple_calls(self):
        p = make_processor(threshold=50.0)
        p.process(80.0)  # on
        for _ in range(10):
            assert p.process(60.0) is True
        p.process(10.0)  # off
        for _ in range(10):
            assert p.process(30.0) is False
