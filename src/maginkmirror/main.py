"""Main entry point for MagInkMirror."""

import logging
import signal
import sys
import time

from typer import Typer

from maginkmirror.core.config import load_config
from maginkmirror.display import make_adapter
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
def main(log_level: str = "INFO", once: bool = False):
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

    scheduler = Scheduler(plugins, layout.render_plugin)

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
