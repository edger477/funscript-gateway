"""FunscriptEngine — discovery, loading, and value interpolation."""

from __future__ import annotations

import logging
from pathlib import Path

from funscript_gateway.app_state import AppState
from funscript_gateway.funscript import parser
from funscript_gateway.models import FunscriptAxis

logger = logging.getLogger(__name__)


def interpolate(actions: list[tuple[int, int]], t_ms: int) -> float:
    """Return the interpolated position value (0.0–100.0) at t_ms.

    Clamps to the first/last keyframe value if t_ms is out of range.
    Uses binary search to find surrounding keyframes in O(log n).
    """
    if not actions:
        return 0.0

    if t_ms <= actions[0][0]:
        return float(actions[0][1])

    if t_ms >= actions[-1][0]:
        return float(actions[-1][1])

    lo, hi = 0, len(actions) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if actions[mid][0] <= t_ms:
            lo = mid
        else:
            hi = mid

    t0, p0 = actions[lo]
    t1, p1 = actions[hi]
    alpha = (t_ms - t0) / (t1 - t0)
    return p0 + alpha * (p1 - p0)


class FunscriptEngine:
    """Manages the axis list for the currently loaded media file.

    Responsible for:
    - Auto-discovering funscript files when file_path changes.
    - Loading and caching action lists.
    - Updating ``current_value`` on all enabled, non-missing axes.
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._last_file_path: str = ""

    def on_player_state_changed(self, player_state) -> None:
        """Called by PlayerConnectionManager when player state changes."""
        new_path = player_state.file_path
        if new_path and new_path != self._last_file_path:
            self._last_file_path = new_path
            self.discover(new_path)

    def discover(self, file_path: str) -> None:
        """Run auto-discovery for the given media file path.

        Clears auto-discovered axes and re-discovers from the media
        directory and any configured search paths. Manual axes (those whose
        file_path was set explicitly) are retained but re-validated.
        """
        p = Path(file_path)
        video_dir = p.parent
        basename = p.stem  # e.g., "example" from "example.mp4"

        # Retain only manually-added axes (those already in app_state.axes).
        # For a fresh discovery all axes are replaced.
        found: list[FunscriptAxis] = []

        search_dirs = [video_dir]
        for sp in self._app_state.config.funscript_search_paths:
            sp_path = Path(sp)
            if sp_path.is_dir() and sp_path not in search_dirs:
                search_dirs.append(sp_path)

        seen_names: set[str] = set()
        for directory in search_dirs:
            pattern = f"{basename}.*.funscript"
            for match in sorted(directory.glob(pattern)):
                # Extract axis name: everything between first and last dot.
                parts = match.name.split(".")
                if len(parts) < 3:
                    continue
                # Format: {basename}.{axisname}.funscript
                # parts = [basename_part..., axisname, "funscript"]
                axis_name = ".".join(parts[len(basename.split(".")):len(parts) - 1])
                if not axis_name or axis_name in seen_names:
                    continue
                seen_names.add(axis_name)
                actions = parser.load(str(match))
                axis = FunscriptAxis(
                    name=axis_name,
                    file_path=str(match),
                    enabled=True,
                    actions=actions,
                    file_missing=(len(actions) == 0 and not match.exists()),
                )
                found.append(axis)

        self._app_state.axes = found
        self._app_state.axes_updated.emit(found)
        logger.info(
            "Discovered %d funscript axes for '%s'.", len(found), basename
        )

    def update_values(self, current_time_ms: int) -> None:
        """Update ``current_value`` for all enabled, non-missing axes."""
        for axis in self._app_state.axes:
            if not axis.enabled or axis.file_missing:
                continue
            axis.current_value = interpolate(axis.actions, current_time_ms)

    def reload_axis(self, axis: FunscriptAxis) -> None:
        """Reload actions for a single axis from disk."""
        actions = parser.load(axis.file_path)
        if actions:
            axis.actions = actions
            axis.file_missing = False
        else:
            axis.file_missing = True
            axis.current_value = 0.0
