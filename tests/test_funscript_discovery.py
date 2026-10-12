"""Tests for funscript file discovery."""

import json
import sys

import pytest

from funscript_gateway.app_state import AppState
from funscript_gateway.funscript.engine import FunscriptEngine
from funscript_gateway.models import FunscriptAxisInput


def _write_funscript(path):
    path.write_text(json.dumps({"actions": [{"at": 0, "pos": 10}, {"at": 1000, "pos": 90}]}))


# Windows forbids "?" and "*" in file names, so such files cannot exist there.
_NOT_ON_WINDOWS = pytest.mark.skipif(
    sys.platform == "win32", reason="'?' and '*' are invalid in Windows file names"
)


@pytest.fixture
def engine():
    return FunscriptEngine(AppState())


class TestDiscover:
    @pytest.mark.parametrize(
        "stem",
        [
            "Plain Video",
            "My Video [1080p]",
            "Scene [VR] [8K]",
            pytest.param("Weird ? mark", marks=_NOT_ON_WINDOWS),
            pytest.param("Star * name", marks=_NOT_ON_WINDOWS),
            "Dotted.name.v2",
        ],
    )
    def test_discovers_axes_for_stems_with_glob_metacharacters(self, engine, tmp_path, stem):
        video = tmp_path / f"{stem}.mp4"
        video.touch()
        _write_funscript(tmp_path / f"{stem}.pitch.funscript")
        _write_funscript(tmp_path / f"{stem}.roll.funscript")

        engine.discover(str(video))

        axes = {a.name: a for a in engine._app_state.axes}
        assert set(axes) == {"pitch", "roll"}
        assert all(not a.file_missing and a.actions for a in axes.values())

    def test_does_not_match_other_videos_sharing_a_prefix(self, engine, tmp_path):
        video = tmp_path / "Scene [1].mp4"
        video.touch()
        _write_funscript(tmp_path / "Scene [1].pitch.funscript")
        _write_funscript(tmp_path / "Scene [2].roll.funscript")

        engine.discover(str(video))

        assert {a.name for a in engine._app_state.axes} == {"pitch"}

    def test_configured_axis_is_populated_for_bracketed_name(self, engine, tmp_path):
        engine._app_state.inputs.append(FunscriptAxisInput(name="pitch", enabled=True))
        video = tmp_path / "Clip [4K].mp4"
        video.touch()
        fs = tmp_path / "Clip [4K].pitch.funscript"
        _write_funscript(fs)

        engine.discover(str(video))

        axis = engine._app_state.axes[0]
        assert axis.file_path == str(fs)
        assert axis.file_missing is False
        assert axis.actions == [(0, 10), (1000, 90)]

    def test_missing_directory_is_ignored(self, engine, tmp_path):
        engine.discover(str(tmp_path / "gone" / "video.mp4"))
        assert engine._app_state.axes == []
