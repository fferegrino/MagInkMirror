import logging

from typer import Typer

from maginkmirror.plugins import PluginRegistry

app = Typer()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("maginkmirror")


@app.command()
def main(log_level: str = "INFO"):

    logging.getLogger().setLevel(log_level.upper())

    log.info("Starting MagInkMirror")

    registry = PluginRegistry({})
    registry.discover()
    plugins = registry.all()

    for plugin in plugins.values():
        log.info("Loaded plugin: %s", plugin.name)
    # scheduler = Scheduler(plugins, render_cb)

    log.info("MagInkMirror started")


if __name__ == "__main__":
    app()
