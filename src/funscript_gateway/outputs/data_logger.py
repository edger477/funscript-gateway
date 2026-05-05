"""Periodic CSV logger for inputs, outputs, and player state."""

from __future__ import annotations

import asyncio
import csv
import datetime
import logging
from pathlib import Path

from funscript_gateway.config import CONFIG_DIR
from funscript_gateway.models import As5311Input, FunscriptAxisInput, HeartRateInput

logger = logging.getLogger(__name__)

DATA_LOG_DIR = CONFIG_DIR / "data_log"


class DataLogger:
    """Samples all inputs, outputs, and player state at a configurable interval and writes CSV.

    The column layout is fixed when the session file is opened (based on inputs/outputs
    present at that moment). Inputs or outputs added later in the same session will not
    appear until the logger is restarted.
    """

    def __init__(self, app_state) -> None:
        self._app_state = app_state
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if not self._app_state.config.data_logging.enabled:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._log_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def _log_loop(self) -> None:
        cfg = self._app_state.config.data_logging
        DATA_LOG_DIR.mkdir(parents=True, exist_ok=True)

        session_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = DATA_LOG_DIR / f"session_{session_ts}.csv"

        # Snapshot input/output lists at session start so columns stay stable.
        fixed_inputs = list(self._app_state.inputs)
        fixed_output_configs = list(self._app_state.config.outputs)

        header = self._build_header(fixed_inputs, fixed_output_configs)
        logger.info("Data logging started: %s", file_path)

        try:
            with file_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(header)

                loop = asyncio.get_event_loop()
                while self._running:
                    t0 = loop.time()
                    row = self._build_row(fixed_inputs, fixed_output_configs)
                    writer.writerow(row)
                    fh.flush()
                    elapsed = loop.time() - t0
                    await asyncio.sleep(max(0.0, cfg.interval_s - elapsed))
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.error("Data logger error: %s", exc)

        logger.info("Data logging stopped: %s", file_path)

    @staticmethod
    def _build_header(inputs: list, output_configs: list) -> list[str]:
        cols = [
            "timestamp",
            "wall_time_s",
            "player_state",
            "player_file",
            "player_time_ms",
            "player_speed",
        ]
        for inp in inputs:
            cols.append(f"{inp.name}_pct")
            if isinstance(inp, As5311Input):
                cols.append(f"{inp.name}_mm")
            elif isinstance(inp, HeartRateInput):
                cols.append(f"{inp.name}_bpm")
        for cfg in output_configs:
            cols.append(f"{cfg.name}_in")
            cols.append(f"{cfg.name}_out")
        return cols

    def _build_row(self, fixed_inputs: list, fixed_output_configs: list) -> list:
        now = datetime.datetime.now()
        ps = self._app_state.player_state

        row: list = [
            now.isoformat(timespec="milliseconds"),
            f"{now.timestamp():.3f}",
            ps.connection_state.name,
            Path(ps.file_path).name if ps.file_path else "",
            ps.current_time_ms,
            f"{ps.playback_speed:.2f}",
        ]

        for inp in fixed_inputs:
            if isinstance(inp, FunscriptAxisInput) and inp.file_missing:
                row.append("")
            else:
                row.append(f"{inp.current_value:.2f}")
            if isinstance(inp, As5311Input):
                row.append(f"{inp.last_position_mm:.4f}")
            elif isinstance(inp, HeartRateInput):
                row.append(str(inp.current_bpm))

        output_inst_map = {out.config.name: out for out in self._app_state.outputs}
        for cfg in fixed_output_configs:
            inst = output_inst_map.get(cfg.name)
            row.append(f"{inst.last_input_value:.2f}" if inst else "")
            row.append(("1" if inst.last_output_state else "0") if inst else "")

        return row
