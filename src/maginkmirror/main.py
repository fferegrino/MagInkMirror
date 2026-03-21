"""Main entry point for MagInkMirror."""

import logging
import signal
import sys
import time
from pathlib import Path

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


@app.command("preview-plugin")
def preview_plugin(
    plugin_name: str,
    out: Path = Option(Path(".maginkmirror") / "preview.png", "--out", help="Output PNG path."),  # noqa: B008
    width: int | None = Option(None, "--width", help="Override render width (px)."),
    height: int | None = Option(None, "--height", help="Override render height (px)."),
):
    """Fetch a plugin once and render it to a PNG (debugging helper)."""
    config = load_config("config.toml")
    display_cfg = config.get("display", {})
    mode = display_cfg.get("mode", "1")
    color_enabled = bool(display_cfg.get("color_enabled", False))
    if color_enabled and mode in {"1", "L"}:
        mode = "RGB"

    registry = PluginRegistry(config)
    registry.discover()
    plugin = registry.get(plugin_name)
    if plugin is None:
        raise SystemExit(f"Plugin not found: {plugin_name!r}")

    zone_cfg = None
    for _, zc in config.get("layout", {}).get("zones", {}).items():
        if zc.get("plugin") == plugin_name:
            zone_cfg = zc
            break

    if width is None:
        width = (
            int(zone_cfg.get("width"))
            if zone_cfg and zone_cfg.get("width") is not None
            else int(display_cfg.get("width", 800))
        )
    if height is None:
        height = (
            int(zone_cfg.get("height"))
            if zone_cfg and zone_cfg.get("height") is not None
            else int(display_cfg.get("height", 480))
        )

    from PIL import Image

    image = Image.new(mode, (width, height), color=(255, 255, 255))

    data = plugin.fetch()
    data = plugin.on_fetch_success(data)

    from maginkmirror.plugins import Zone

    plugin.render(data, image, Zone(x=0, y=0, width=width, height=height))

    out.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(out)
    log.info("Preview saved: %s", out)


@app.command("run")
def main(
    log_level: str = "INFO",
    once: bool = False,
    show_zones: bool = Option(False, "--show-zones", help="Render a zone overlay frame (for layout debugging)."),
):
    """Start MagInkMirror."""
    logging.getLogger().setLevel(log_level.upper())

    log.info("Starting MagInkMirror")
    config = load_config("config.toml")

    registry = PluginRegistry(config)
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
