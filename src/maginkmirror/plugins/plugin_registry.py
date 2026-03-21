"""Plugin registry – discovers and instantiates plugins."""

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maginkmirror.plugins.base_plugin import BasePlugin

log = logging.getLogger(__name__)

# Keys under `[layout.zones.<name>]` that are geometry / routing only. Any other
# key is merged into the plugin config for that zone (separate instance).
LAYOUT_ZONE_KEYS = frozenset({"plugin", "x", "y", "width", "height"})

_CONTRIB_PLUGINS_DIR = Path(__file__).parent.parent / "contrib" / "plugins"

# Folder that ships with MagInkMirror
_BUILTIN_PLUGINS_DIR = Path(__file__).parent.parent / "plugins"


class PluginRegistry:
    """
    Discover and instantiate plugins from the built-in and extra plugin directories.

    Loads plugins from:
      1. The built-in `plugins/` directory.
      2. The `contrib/plugins/` directory.
      3. Any extra directories listed in config['plugin_dirs'].

    Each plugin directory must contain a module called `plugin.py`
    with a class that subclasses BasePlugin.  The class name is
    looked up from the module's ``PLUGIN_CLASS`` attribute, or
    falls back to the first BasePlugin subclass found.

    Example layout::

        plugins/
            weather/
                plugin.py      ← defines WeatherPlugin(BasePlugin)
            clock/
                plugin.py      ← defines ClockPlugin(BasePlugin)
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self._plugins: dict[str, BasePlugin] = {}
        # plugin kind (directory name) -> path to plugin.py, for all discovered dirs
        self._plugin_paths_for_kind: dict[str, Path] = {}

    def _build_plugin_config(self, plugin_config: dict) -> dict:
        """
        Create the config passed to a plugin instance.

        Merge order (later wins):

        1. ``[location]`` — shared timezone, coordinates, place/region (optional).
        2. ``[plugins.<name>]`` — plugin-specific overrides.
        3. ``[fonts]`` — exposed for ``maginkmirror.core.fonts.load_font`` and similar.
        """
        merged: dict = {}
        loc = self.config.get("location")
        if isinstance(loc, dict):
            merged.update(loc)
        if isinstance(plugin_config, dict):
            merged.update(plugin_config)

        if isinstance(self.config.get("fonts"), dict):
            merged["fonts"] = self.config["fonts"]
        return merged

    # ------------------------------------------------------------------

    def discover(self) -> None:
        """Scan plugin directories and instantiate enabled plugins."""
        search_dirs = [_BUILTIN_PLUGINS_DIR, _CONTRIB_PLUGINS_DIR]
        for extra in self.config.get("plugin_dirs", []):
            search_dirs.append(Path(extra))

        enabled: list[str] = self.config.get("enabled_plugins", [])
        plugins_conf: dict = self.config.get("plugins", {})

        for directory in search_dirs:
            if not directory.is_dir():
                log.warning("Plugin dir not found: %s", directory)
                continue
            for plugin_dir in sorted(directory.iterdir()):
                if not plugin_dir.is_dir():
                    continue
                name = plugin_dir.name
                plugin_file = plugin_dir / "plugin.py"
                if not plugin_file.exists():
                    log.debug("Skipping %s – no plugin.py", name)
                    continue
                self._plugin_paths_for_kind[name] = plugin_file
                if enabled and name not in enabled:
                    continue
                try:
                    instance = self._load(name, plugin_file, plugins_conf.get(name, {}))
                    self._plugins[name] = instance
                    log.info("Loaded plugin: %s (interval=%ds)", name, instance.interval)
                except Exception as exc:
                    log.error("Failed to load plugin %s: %s", name, exc)

        self.ensure_zone_instances()
        self.prune_plugins_to_layout()

    def ensure_zone_instances(self) -> None:
        """
        For each layout zone with keys beyond geometry, load a separate plugin
        instance keyed by the zone name so fetch/render use merged config.

        Merge order for that instance: ``[location]``, ``[plugins.<kind>]``,
        then zone-specific keys (e.g. latitude, feed_url).
        """
        plugins_conf: dict = self.config.get("plugins", {})
        layout_zones = self.config.get("layout", {}).get("zones", {})

        for zone_name, zone_cfg in layout_zones.items():
            if not isinstance(zone_cfg, dict) or "plugin" not in zone_cfg:
                continue
            plugin_kind = zone_cfg["plugin"]
            extras = {k: v for k, v in zone_cfg.items() if k not in LAYOUT_ZONE_KEYS}
            if not extras:
                continue
            path = self._plugin_paths_for_kind.get(plugin_kind)
            if path is None:
                log.error(
                    "Zone %r uses plugin kind %r but no plugin.py exists for that name",
                    zone_name,
                    plugin_kind,
                )
                continue
            merged = dict(plugins_conf.get(plugin_kind, {}))
            merged.update(extras)
            try:
                instance = self._load(zone_name, path, merged)
                self._plugins[zone_name] = instance
                log.info(
                    "Loaded zone plugin instance: %s (kind=%s, interval=%ds)",
                    zone_name,
                    plugin_kind,
                    instance.interval,
                )
            except Exception as exc:
                log.error("Failed to load zone plugin instance %s: %s", zone_name, exc)

    def prune_plugins_to_layout(self) -> None:
        """
        Drop plugin instances that no layout zone references.

        Scheduler keys are plugin kind (e.g. ``weather``) when a zone has no
        extras, or the zone table name when it has merged keys.
        """
        layout_zones = self.config.get("layout", {}).get("zones", {})
        if not layout_zones:
            return

        keys: set[str] = set()
        for zone_name, zone_cfg in layout_zones.items():
            if not isinstance(zone_cfg, dict) or "plugin" not in zone_cfg:
                continue
            extras = {k: v for k, v in zone_cfg.items() if k not in LAYOUT_ZONE_KEYS}
            instance_key = zone_name if extras else zone_cfg["plugin"]
            keys.add(instance_key)

        if not keys:
            return

        self._plugins = {k: v for k, v in self._plugins.items() if k in keys}

    def _load(self, name: str, path: Path, config: dict) -> "BasePlugin":
        module_name = f"inkmirror_plugin_{name}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        from maginkmirror.plugins.base_plugin import BasePlugin  # local import to avoid circulars

        # Prefer explicit PLUGIN_CLASS attribute
        if hasattr(module, "PLUGIN_CLASS"):
            cls = getattr(module, module.PLUGIN_CLASS)
        else:
            candidates = [
                v
                for v in vars(module).values()
                if isinstance(v, type) and issubclass(v, BasePlugin) and v is not BasePlugin
            ]
            if not candidates:
                raise ImportError(f"No BasePlugin subclass found in {path}")
            cls = candidates[0]

        return cls(self._build_plugin_config(config))

    def all(self) -> dict[str, "BasePlugin"]:
        """Get all plugins."""
        return dict(self._plugins)

    def get(self, name: str) -> "BasePlugin | None":
        """Get a plugin by name."""
        return self._plugins.get(name)
