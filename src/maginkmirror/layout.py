"""Layout engine – composites plugin output into a single display image."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from PIL import Image

from maginkmirror.plugins import BasePlugin, PluginData, Zone

log = logging.getLogger(__name__)


@dataclass
class ZoneConfig:
    """Configuration for a display zone."""

    plugin: str
    """The plugin to render in this zone."""

    zone: Zone
    """The zone to render in."""


class LayoutEngine:
    """
    Holds the master display image (1-bit or greyscale depending on the display driver).

    When a plugin's data changes, render() repaints just that zone,
    then hands the composite image to the display adapter.

    Zone assignment is driven by config::

        [layout.zones.clock]
        plugin = "clock"
        x = 0
        y = 0
        width = 400
        height = 120

    The display adapter receives the full image after every render cycle;
    it decides whether to do a full or partial refresh.
    """

    def __init__(
        self,
        width: int,
        height: int,
        plugins: dict[str, BasePlugin],
        zones: list[ZoneConfig],
        display_adapter,
        mode: str = "1",  # "1" = 1-bit, "L" = 8-bit grey
        min_refresh_interval: float = 0.0,
    ) -> None:
        self._width = width
        self._height = height
        self._plugins = plugins
        self._zones = zones
        self._adapter = display_adapter
        self._mode = mode
        self._image = Image.new(mode, (width, height), color=255)  # white canvas
        self._lock = threading.Lock()
        self._dirty_zones: set[str] = set()
        self._min_refresh_interval = float(min_refresh_interval)
        self._last_refresh_at: float = 0.0
        self._refresh_timer: threading.Timer | None = None

    # ------------------------------------------------------------------

    def render_plugin(self, plugin_name: str, data: PluginData) -> None:
        """
        Render a plugin into the display.

        Called by the scheduler when a plugin has new data.
        """
        if not data.changed and data.error is None:
            log.debug("[%s] no change – skipping render", plugin_name)
            return

        matching = [zc for zc in self._zones if zc.plugin == plugin_name]
        if not matching:
            log.debug("[%s] no zone configured – skipping", plugin_name)
            return

        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            return

        with self._lock:
            for zc in matching:
                # Create a blank zone-sized image and let the plugin draw into it
                zone_img = Image.new(self._mode, (zc.zone.width, zc.zone.height), color=255)
                try:
                    plugin.render(data, zone_img, zc.zone)
                except Exception as exc:
                    log.error("[%s] render raised: %s", plugin_name, exc)
                    continue
                # Paste into master image
                self._image.paste(zone_img, (zc.zone.x, zc.zone.y))
                self._dirty_zones.add(plugin_name)

        self._flush()

    def _flush(self, *, force: bool = False) -> None:
        now = time.monotonic()

        if not force and self._min_refresh_interval > 0:
            remaining = self._min_refresh_interval - (now - self._last_refresh_at)
            if remaining > 0:
                with self._lock:
                    if self._refresh_timer is None or not self._refresh_timer.is_alive():
                        self._refresh_timer = threading.Timer(remaining, self._flush, kwargs={"force": True})
                        self._refresh_timer.daemon = True
                        self._refresh_timer.start()
                return

        with self._lock:
            dirty = set(self._dirty_zones)
            self._dirty_zones.clear()
            if force:
                self._refresh_timer = None

        if not dirty:
            return

        if self._min_refresh_interval > 0:
            self._last_refresh_at = now

        try:
            self._adapter.display(self._image.copy(), dirty_plugins=dirty)
        except Exception as exc:
            log.error("Display adapter error: %s", exc)

    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: dict,
        plugins: dict[str, BasePlugin],
        display_adapter,
    ) -> LayoutEngine:
        """Create a layout engine from a configuration."""
        display_cfg = config.get("display", {})
        width = display_cfg.get("width", 800)
        height = display_cfg.get("height", 480)
        mode = display_cfg.get("mode", "1")
        min_refresh_interval = display_cfg.get("min_display_refresh_interval", 0.0)

        zones: list[ZoneConfig] = []
        for zone_name, zone_cfg in config.get("layout", {}).get("zones", {}).items():
            zones.append(
                ZoneConfig(
                    plugin=zone_cfg["plugin"],
                    zone=Zone(
                        x=zone_cfg.get("x", 0),
                        y=zone_cfg.get("y", 0),
                        width=zone_cfg.get("width", width),
                        height=zone_cfg.get("height", height),
                    ),
                )
            )
            log.debug("Zone '%s' → plugin '%s'", zone_name, zone_cfg["plugin"])

        return cls(width, height, plugins, zones, display_adapter, mode, min_refresh_interval=float(min_refresh_interval))
