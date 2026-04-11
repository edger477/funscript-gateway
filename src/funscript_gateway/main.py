"""Entry point for funscript-gateway."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from funscript_gateway.config import CONFIG_DIR, LOG_PATH, load_config, save_config


def setup_logging(debug: bool = False) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=1 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[handler],
    )
    # Also log to stderr so the user sees output when running from a terminal.
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(console)


logger = logging.getLogger(__name__)


async def async_main(app_state, player_manager, engine, output_manager) -> None:
    """Start all async components and keep running until cancelled."""
    await player_manager.start()
    await output_manager.start()
    try:
        # Run until QApplication quits (which cancels the event loop).
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down…")
        await output_manager.stop()
        await player_manager.stop()
        try:
            save_config(app_state.config)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to save config on shutdown: %s", exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="funscript-gateway")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(debug=args.debug)
    logger.info("funscript-gateway starting.")

    # Qt must be imported after logging setup.
    from PySide6.QtWidgets import QApplication
    import qasync

    from funscript_gateway.app_state import AppState
    from funscript_gateway.funscript.engine import FunscriptEngine
    from funscript_gateway.outputs.manager import OutputManager
    from funscript_gateway.player.manager import PlayerConnectionManager
    from funscript_gateway.ui.main_window import MainWindow
    from funscript_gateway.ui.tray import SystemTrayIcon

    app = QApplication(sys.argv)
    app.setApplicationName("funscript-gateway")
    app.setQuitOnLastWindowClosed(False)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Build shared state.
    app_state = AppState()
    app_state.config = load_config()
    app_state.axes = list(app_state.config.axes)

    # Build components.
    player_manager = PlayerConnectionManager(app_state)
    engine = FunscriptEngine(app_state)
    output_manager = OutputManager(app_state, engine)

    # Connect player state changes to the funscript engine.
    app_state.player_state_changed.connect(engine.on_player_state_changed)

    # Build UI.
    window = MainWindow(app_state, engine, output_manager, player_manager)
    tray = SystemTrayIcon(window, app_state)
    tray.show()
    window.show()

    def on_quit() -> None:
        for task in asyncio.all_tasks(loop):
            task.cancel()

    app.aboutToQuit.connect(on_quit)

    with loop:
        loop.run_until_complete(
            async_main(app_state, player_manager, engine, output_manager)
        )

    logger.info("funscript-gateway exited.")


if __name__ == "__main__":
    main()
