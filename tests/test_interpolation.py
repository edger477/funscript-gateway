"""Tests for funscript value interpolation."""

import pytest

from funscript_gateway.funscript.engine import interpolate


class TestInterpolate:
    def test_empty_actions_returns_zero(self):
        assert interpolate([], 0) == 0.0
        assert interpolate([], 5000) == 0.0

    def test_single_keyframe_before_clamps(self):
        actions = [(1000, 75)]
        assert interpolate(actions, 0) == 75.0
        assert interpolate(actions, 500) == 75.0

    def test_single_keyframe_after_clamps(self):
        actions = [(1000, 75)]
        assert interpolate(actions, 1000) == 75.0
        assert interpolate(actions, 9999) == 75.0

    def test_before_first_keyframe_clamps_to_first(self):
        actions = [(1000, 20), (2000, 80)]
        result = interpolate(actions, 0)
        assert result == 20.0

    def test_at_first_keyframe_exact(self):
        actions = [(1000, 20), (2000, 80)]
        result = interpolate(actions, 1000)
        assert result == 20.0

    def test_after_last_keyframe_clamps_to_last(self):
        actions = [(1000, 20), (2000, 80)]
        result = interpolate(actions, 9999)
        assert result == 80.0

    def test_at_last_keyframe_exact(self):
        actions = [(1000, 20), (2000, 80)]
        result = interpolate(actions, 2000)
        assert result == 80.0

    def test_midpoint_between_two_keyframes(self):
        actions = [(0, 0), (1000, 100)]
        result = interpolate(actions, 500)
        assert result == pytest.approx(50.0)

    def test_quarter_point_interpolation(self):
        actions = [(0, 0), (1000, 100)]
        result = interpolate(actions, 250)
        assert result == pytest.approx(25.0)

    def test_three_quarter_point_interpolation(self):
        actions = [(0, 0), (1000, 100)]
        result = interpolate(actions, 750)
        assert result == pytest.approx(75.0)

    def test_interpolation_between_non_zero_keyframes(self):
        # From spec example: at=0->0, at=1000->75, at=2500->20, at=3200->100
        actions = [(0, 0), (1000, 75), (2500, 20), (3200, 100)]
        # Midpoint between 0 and 1000: 500ms
        result = interpolate(actions, 500)
        assert result == pytest.approx(37.5)

    def test_interpolation_exact_match_middle_keyframe(self):
        actions = [(0, 0), (1000, 75), (2500, 20), (3200, 100)]
        result = interpolate(actions, 1000)
        assert result == pytest.approx(75.0)

    def test_interpolation_between_second_and_third_keyframes(self):
        actions = [(0, 0), (1000, 75), (2500, 20), (3200, 100)]
        # Midpoint between 1000 and 2500 = 1750ms
        # alpha = (1750-1000)/(2500-1000) = 750/1500 = 0.5
        # value = 75 + 0.5*(20-75) = 75 - 27.5 = 47.5
        result = interpolate(actions, 1750)
        assert result == pytest.approx(47.5)

    def test_many_keyframes_binary_search(self):
        # 1000 evenly spaced keyframes; test a few points
        actions = [(i * 10, i % 101) for i in range(1000)]
        # At t=500 (index 50 exactly)
        result = interpolate(actions, 500)
        assert result == pytest.approx(float(actions[50][1]))

    def test_result_float_type(self):
        actions = [(0, 50), (1000, 100)]
        result = interpolate(actions, 500)
        assert isinstance(result, float)

    def test_decreasing_values_interpolation(self):
        actions = [(0, 100), (1000, 0)]
        result = interpolate(actions, 400)
        assert result == pytest.approx(60.0)

    def test_boundary_exactly_at_zero(self):
        actions = [(0, 50), (500, 100)]
        result = interpolate(actions, 0)
        assert result == 50.0
