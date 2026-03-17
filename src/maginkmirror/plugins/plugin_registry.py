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
                if enabled and name not in enabled:
                    continue
                plugin_file = plugin_dir / "plugin.py"
                if not plugin_file.exists():
                    log.debug("Skipping %s – no plugin.py", name)
                    continue
                try:
                    instance = self._load(name, plugin_file, plugins_conf.get(name, {}))
                    self._plugins[name] = instance
                    log.info("Loaded plugin: %s (interval=%ds)", name, instance.interval)
                except Exception as exc:
                    log.error("Failed to load plugin %s: %s", name, exc)

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

        return cls(config)

    # ------------------------------------------------------------------

    def all(self) -> dict[str, "BasePlugin"]:
        """Get all plugins."""
        return dict(self._plugins)

    def get(self, name: str) -> "BasePlugin | None":
        """Get a plugin by name."""
        return self._plugins.get(name)
