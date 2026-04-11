"""Funscript JSON parser."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def load(path: str) -> list[tuple[int, int]]:
    """Load a funscript file and return sorted (at_ms, pos) pairs.

    Returns an empty list on any error (missing file, invalid JSON, etc.).
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        actions = [(int(a["at"]), int(a["pos"])) for a in data["actions"]]
        actions.sort(key=lambda x: x[0])
        return actions
    except FileNotFoundError:
        logger.debug("Funscript file not found: %s", path)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load funscript %s: %s", path, exc)
        return []
