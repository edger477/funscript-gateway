"""Fire-and-forget task helper.

asyncio only keeps weak references to tasks, so a task started with
``ensure_future`` and not stored anywhere can be garbage-collected mid-run,
and its exception is reported (if at all) only as "Task exception was never
retrieved".  ``spawn`` keeps a strong reference until the task finishes and
logs any exception it raised.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Coroutine

logger = logging.getLogger(__name__)

_background: set[asyncio.Task] = set()


def spawn(coro: Coroutine, name: str = "") -> asyncio.Task:
    task = asyncio.ensure_future(coro)
    _background.add(task)
    task.add_done_callback(lambda t: _on_done(t, name))
    return task


def _on_done(task: asyncio.Task, name: str) -> None:
    _background.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Background task %s failed", name or task.get_name(), exc_info=exc
        )
