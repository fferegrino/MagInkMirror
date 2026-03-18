"""Layout engine – composites plugin output into a single display image."""

from __future__ import annotations

import logging
import threading
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
    ) -> None:
        self._width = width
        self._height = height
        self._plugins = plugins
        self._zones = zones
        self._adapter = display_adapter
        self._mode = mode
        self._image = Image.new(mode, (width, height), color=255)  # white canvas
        self._lock = threading.Lock()

    # ------------------------------------------------------------------

    def render_updates(self, updates: dict[str, PluginData]) -> None:
        """
        Render multiple plugin updates into the master image and flush once.

        This is the preferred path when the display refresh cadence is global.
        """
        dirty: set[str] = set()
        for plugin_name, data in updates.items():
            if self._render_into_image(plugin_name, data):
                dirty.add(plugin_name)

        if dirty:
            self._flush(dirty)

    def render_plugin(self, plugin_name: str, data: PluginData) -> None:
        """
        Render a plugin into the display.

        Called by the scheduler when a plugin has new data.
        """
        if self._render_into_image(plugin_name, data):
            self._flush({plugin_name})

    def _render_into_image(self, plugin_name: str, data: PluginData) -> bool:
        if not data.changed and data.error is None:
            log.debug("[%s] no change – skipping render", plugin_name)
            return False

        matching = [zc for zc in self._zones if zc.plugin == plugin_name]
        if not matching:
            log.debug("[%s] no zone configured – skipping", plugin_name)
            return False

        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            return False

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
        return True

    def _flush(self, dirty_plugins: set[str]) -> None:
        try:
            self._adapter.display(self._image.copy(), dirty_plugins=dirty_plugins)
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

        return cls(width, height, plugins, zones, display_adapter, mode)
