"""PyInstaller build script for funscript-gateway.

Run with:
    python scripts/build.py

Produces a single-file Windows executable in the dist/ directory.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT = ROOT / "src" / "funscript_gateway" / "main.py"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"


def main() -> None:
    if not ENTRY_POINT.exists():
        print(f"Entry point not found: {ENTRY_POINT}", file=sys.stderr)
        sys.exit(1)

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(ENTRY_POINT),
        "--onefile",
        "--windowed",
        "--name",
        "funscript-gateway",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        # Hidden imports for packages that PyInstaller may not detect automatically.
        "--hidden-import",
        "paho",
        "--hidden-import",
        "paho.mqtt",
        "--hidden-import",
        "paho.mqtt.client",
        "--hidden-import",
        "qasync",
        "--hidden-import",
        "PySide6.QtCore",
        "--hidden-import",
        "PySide6.QtGui",
        "--hidden-import",
        "PySide6.QtWidgets",
        "--hidden-import",
        "tomllib",
        "--hidden-import",
        "tomli_w",
        # Collect all subpackages of funscript_gateway.
        "--collect-all",
        "funscript_gateway",
        # Clean previous build artefacts before building.
        "--clean",
    ]

    print("Building funscript-gateway with PyInstaller…")
    print("Command:", " ".join(args))
    result = subprocess.run(args, cwd=str(ROOT))
    if result.returncode != 0:
        print("PyInstaller build failed.", file=sys.stderr)
        sys.exit(result.returncode)
    print(f"Build complete. Executable: {DIST_DIR / 'funscript-gateway.exe'}")


if __name__ == "__main__":
    main()
