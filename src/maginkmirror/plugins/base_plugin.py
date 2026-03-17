"""Base class for all MagInkMirror plugins."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

log = logging.getLogger(__name__)


@dataclass
class Zone:
    """A rectangular region on the display in pixels."""

    x: int
    y: int
    width: int
    height: int


@dataclass
class PluginData:
    """Container returned by every plugin's fetch() call."""

    payload: Any  # plugin-specific data (dict, str, etc.)
    error: str | None = None  # set if fetch failed – last-good data is reused
    changed: bool = True  # set False to skip re-render (no new data)
    metadata: dict = field(default_factory=dict)


class BasePlugin(ABC):
    """
    All plugins must subclass BasePlugin and implement fetch() and render().

    Lifecycle
    ---------
    1. __init__(config)  – called once at startup
    2. fetch()           – called on a background thread every `interval` seconds
    3. render(data, img, zone) – called on the main thread when fetch() returns
                                 new data; draw into `img` inside `zone`
    """

    #: How often (seconds) the scheduler calls fetch(). Override in subclass.
    interval: int = 60

    #: Friendly name shown in logs and the config file.
    name: str = "unnamed"

    def __init__(self, config: dict) -> None:
        self.config = config
        self._last_good: PluginData | None = None

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch(self) -> PluginData:
        """
        Retrieve fresh data (may block – runs in a thread pool).

        Return a PluginData.  If the fetch fails, set error= and the
        scheduler will reuse the last-good payload for rendering.
        """

    @abstractmethod
    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        """
        Draw into `image` within `zone` using Pillow.

        The image is always 1-bit or 4-bit grey depending on the display
        driver; avoid anti-aliased fills that bleed to unexpected colours.
        """

    # ------------------------------------------------------------------
    # Helpers available to subclasses
    # ------------------------------------------------------------------

    def on_fetch_success(self, data: PluginData) -> PluginData:
        """
        Return the data to the scheduler.

        Called by the scheduler after a successful fetch.
        """
        self._last_good = data
        return data

    def on_fetch_error(self, exc: Exception) -> PluginData | None:
        """
        Return the data to the scheduler.

        Called by the scheduler when fetch() raises.
        Return last-good or None.
        """
        log.warning("[%s] fetch failed: %s – using last-good data", self.name, exc)
        if self._last_good:
            stale = PluginData(
                payload=self._last_good.payload,
                error=str(exc),
                changed=False,
                metadata=self._last_good.metadata,
            )
            return stale
        return None
