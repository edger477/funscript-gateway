"""ThresholdSwitchProcessor — converts a 0-100 float into a boolean on/off state."""

from __future__ import annotations

from funscript_gateway.models import ThresholdSwitchConfig


class ThresholdSwitchProcessor:
    """Stateful threshold switch with optional hysteresis.

    The hysteresis dead band is centered on the threshold:
        upper_edge = threshold + hysteresis / 2
        lower_edge = threshold - hysteresis / 2

    When active_high is True (default):
        OFF -> ON  when value >= upper_edge
        ON  -> OFF when value <  lower_edge

    When active_high is False the output is inverted.
    """

    def __init__(self, config: ThresholdSwitchConfig) -> None:
        self.config = config
        self._current_state: bool = False

    def process(self, value: float) -> bool:
        cfg = self.config
        half = cfg.hysteresis / 2.0

        if self._current_state:
            switch_off = cfg.threshold - half
            if value < switch_off:
                self._current_state = False
        else:
            switch_on = cfg.threshold + half
            if value >= switch_on:
                self._current_state = True

        return self._current_state if cfg.active_high else not self._current_state
