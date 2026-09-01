"""Build a Linux AppImage for funscript-gateway.

Run with:
    python scripts/build_appimage.py

Steps:
    1. PyInstaller one-dir build  -> dist/funscript-gateway/
    2. Assemble an AppDir around that build
    3. Download appimagetool (cached in build/) if missing
    4. Package               -> dist/funscript-gateway-x86_64.AppImage

The resulting AppImage is built against this machine's glibc, so it needs a
target system with an equal or newer glibc. The GitHub release workflow builds
it on ubuntu-22.04 for broad compatibility.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT = ROOT / "src" / "funscript_gateway" / "main.py"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
PACKAGING_DIR = ROOT / "packaging"
APP_NAME = "funscript-gateway"
ARCH = os.environ.get("ARCH", "x86_64")

APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/continuous/"
    f"appimagetool-{ARCH}.AppImage"
)


def _run(args: list[str], **kwargs) -> None:
    print("+", " ".join(str(a) for a in args))
    result = subprocess.run(args, cwd=str(ROOT), **kwargs)
    if result.returncode != 0:
        sys.exit(result.returncode)


def build_pyinstaller() -> Path:
    """One-dir PyInstaller build. Returns the output directory."""
    out_dir = DIST_DIR / APP_NAME
    if out_dir.is_dir():
        shutil.rmtree(out_dir)
    elif out_dir.exists():
        out_dir.unlink()  # stale one-file build from scripts/build.py
    _run([
        sys.executable, "-m", "PyInstaller",
        str(ENTRY_POINT),
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--name", APP_NAME,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(BUILD_DIR),
        "--hidden-import", "paho",
        "--hidden-import", "paho.mqtt",
        "--hidden-import", "paho.mqtt.client",
        "--hidden-import", "qasync",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "tomllib",
        "--hidden-import", "tomli_w",
        "--collect-all", "funscript_gateway",
        "--clean",
    ])
    exe = out_dir / APP_NAME
    if not exe.exists():
        print(f"PyInstaller output not found: {exe}", file=sys.stderr)
        sys.exit(1)
    return out_dir


def assemble_appdir(pyinstaller_dir: Path) -> Path:
    appdir = BUILD_DIR / "AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)

    bin_dir = appdir / "usr" / "bin"
    bin_dir.mkdir(parents=True)
    # Copy the whole one-dir bundle into usr/bin.
    for item in pyinstaller_dir.iterdir():
        dest = bin_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    icon_src = PACKAGING_DIR / f"{APP_NAME}.png"
    desktop_src = PACKAGING_DIR / f"{APP_NAME}.desktop"

    apps_dir = appdir / "usr" / "share" / "applications"
    apps_dir.mkdir(parents=True)
    shutil.copy2(desktop_src, apps_dir / f"{APP_NAME}.desktop")

    icons_dir = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icons_dir.mkdir(parents=True)
    shutil.copy2(icon_src, icons_dir / f"{APP_NAME}.png")

    # appimagetool expects the desktop file and icon at the AppDir root.
    shutil.copy2(desktop_src, appdir / f"{APP_NAME}.desktop")
    shutil.copy2(icon_src, appdir / f"{APP_NAME}.png")
    shutil.copy2(icon_src, appdir / ".DirIcon")

    apprun = appdir / "AppRun"
    apprun.write_text(
        "#!/bin/sh\n"
        'HERE="$(dirname "$(readlink -f "$0")")"\n'
        'export PATH="$HERE/usr/bin:$PATH"\n'
        f'exec "$HERE/usr/bin/{APP_NAME}" "$@"\n'
    )
    apprun.chmod(apprun.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return appdir


def fetch_appimagetool() -> Path:
    tool = BUILD_DIR / f"appimagetool-{ARCH}.AppImage"
    if not tool.exists():
        print(f"Downloading {APPIMAGETOOL_URL}")
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(APPIMAGETOOL_URL, tool)  # noqa: S310
    tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    return tool


def package(appdir: Path, tool: Path) -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    out = DIST_DIR / f"{APP_NAME}-{ARCH}.AppImage"
    if out.exists():
        out.unlink()
    env = {**os.environ, "ARCH": ARCH}
    _run(
        [str(tool), "--appimage-extract-and-run", str(appdir), str(out)],
        env=env,
    )
    out.chmod(out.stat().st_mode | stat.S_IEXEC)
    return out


def main() -> None:
    if not ENTRY_POINT.exists():
        print(f"Entry point not found: {ENTRY_POINT}", file=sys.stderr)
        sys.exit(1)
    pyinstaller_dir = build_pyinstaller()
    appdir = assemble_appdir(pyinstaller_dir)
    tool = fetch_appimagetool()
    out = package(appdir, tool)
    print(f"\nBuild complete: {out} ({out.stat().st_size / 1_048_576:.1f} MiB)")


if __name__ == "__main__":
    main()
