"""Main entry point for MagInkMirror."""

import logging
import signal
import sys
import time

from typer import Option, Typer

from maginkmirror.core.config import load_config
from maginkmirror.display.make_adapter import make_adapter
from maginkmirror.layout import LayoutEngine
from maginkmirror.plugins import PluginRegistry
from maginkmirror.scheduler import Scheduler

app = Typer()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("maginkmirror")


@app.command()
def main(
    log_level: str = "INFO",
    once: bool = False,
    show_zones: bool = Option(False, "--show-zones", help="Render a zone overlay frame (for layout debugging)."),
):
    """Start MagInkMirror."""
    logging.getLogger().setLevel(log_level.upper())

    log.info("Starting MagInkMirror")

    registry = PluginRegistry({})
    registry.discover()
    plugins = registry.all()

    config = load_config("config.toml")

    adapter = make_adapter(config)

    for plugin in plugins.values():
        log.info("Loaded plugin: %s", plugin.name)

    layout = LayoutEngine.from_config(config, plugins, adapter)

    if show_zones:
        layout.display_zone_overlay()
        return

    display_cfg = config.get("display", {})
    scheduler = Scheduler(
        plugins,
        layout.render_plugin,
        layout.render_updates,
        display_refresh_interval=float(display_cfg.get("display_refresh_interval", -1.0)),
    )

    def _shutdown(sig, frame):
        """Shutdown the application gracefully."""
        log.info("Shutting down (signal %s)...", sig)
        scheduler.stop()
        adapter.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    scheduler.start()

    if not once:
        log.info("Running in background mode")
        while True:
            time.sleep(1)

    log.info("MagInkMirror started")


if __name__ == "__main__":
    app()
