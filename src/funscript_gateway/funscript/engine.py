"""FunscriptEngine — discovery, loading, and value interpolation."""

from __future__ import annotations

import logging
from pathlib import Path

from funscript_gateway.app_state import AppState
from funscript_gateway.funscript import parser
from funscript_gateway.models import FunscriptAxisInput

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
    """Manages funscript axis inputs for the currently loaded media file.

    Responsible for:
    - Resolving funscript files for configured FunscriptAxisInput names when file_path changes.
    - Loading and caching action lists.
    - Updating ``current_value`` on all enabled FunscriptAxisInputs each tick.
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
        """Resolve funscript files for the given media file path.

        For each configured FunscriptAxisInput, looks for a matching file
        ``{video_basename}.{axis_name}.funscript`` in the video directory and
        any configured search paths.  Updates each axis's runtime fields
        (file_path, actions, file_missing, current_value).

        Also discovers any matching files whose axis name is not yet in the
        inputs list and appends them as new FunscriptAxisInput objects.
        """
        p = Path(file_path)
        video_dir = p.parent
        basename = p.stem

        search_dirs = [video_dir]
        for sp in self._app_state.config.funscript_search_paths:
            sp_path = Path(sp)
            if sp_path.is_dir() and sp_path not in search_dirs:
                search_dirs.append(sp_path)

        # Find all funscript files matching the video basename
        found_files: dict[str, Path] = {}
        for directory in search_dirs:
            pattern = f"{basename}.*.funscript"
            for match in sorted(directory.glob(pattern)):
                parts = match.name.split(".")
                if len(parts) < 3:
                    continue
                axis_name = ".".join(parts[len(basename.split(".")):len(parts) - 1])
                if axis_name and axis_name not in found_files:
                    found_files[axis_name] = match

        # Update existing configured FunscriptAxisInputs
        configured_names: set[str] = set()
        for inp in self._app_state.inputs:
            if not isinstance(inp, FunscriptAxisInput):
                continue
            configured_names.add(inp.name)
            if inp.name in found_files:
                fpath = found_files[inp.name]
                actions = parser.load(str(fpath))
                inp.file_path = str(fpath)
                inp.actions = actions
                inp.file_missing = not actions
            else:
                inp.file_path = ""
                inp.actions = []
                inp.file_missing = True
                inp.current_value = inp.default_value * 100.0

        # Append auto-discovered axes not yet configured
        for axis_name, fpath in found_files.items():
            if axis_name not in configured_names:
                actions = parser.load(str(fpath))
                new_inp = FunscriptAxisInput(
                    name=axis_name,
                    enabled=True,
                    default_value=0.0,
                    file_path=str(fpath),
                    actions=actions,
                    file_missing=not actions,
                )
                self._app_state.inputs.append(new_inp)

        self._app_state.inputs_updated.emit(self._app_state.inputs)
        logger.info(
            "Discovered %d funscript files for '%s'.", len(found_files), basename
        )

    def update_values(self, current_time_ms: int) -> None:
        """Update ``current_value`` for all enabled FunscriptAxisInputs."""
        for inp in self._app_state.inputs:
            if not isinstance(inp, FunscriptAxisInput) or not inp.enabled:
                continue
            if inp.file_missing or not inp.actions:
                inp.current_value = inp.default_value * 100.0
            else:
                inp.current_value = interpolate(inp.actions, current_time_ms)

    def reload_axis(self, axis: FunscriptAxisInput) -> None:
        """Reload actions for a single axis from disk."""
        if not axis.file_path:
            return
        actions = parser.load(axis.file_path)
        if actions:
            axis.actions = actions
            axis.file_missing = False
        else:
            axis.file_missing = True
            axis.current_value = axis.default_value * 100.0
