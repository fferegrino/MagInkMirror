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

    @property
    def midpoint(self) -> tuple[float, float]:
        """
        Return the (x, y) midpoint of the zone in pixels (float).

        Midpoint is computed relative to the zone's top-left corner.
        For example, if `width` is even, the midpoint will fall between two
        pixel columns.
        """
        return (self.x + (self.width / 2), self.y + (self.height / 2))

    @property
    def midpoint_int(self) -> tuple[int, int]:
        """
        Return the (x, y) midpoint of the zone in pixels (int).

        Uses `round()` to turn the float midpoint into integer pixel coords.
        """
        mx, my = self.midpoint
        return (int(round(mx)), int(round(my)))

    # ------------------------------------------------------------------
    # Basic geometry accessors
    # ------------------------------------------------------------------

    @property
    def top_left(self) -> tuple[int, int]:
        """Return the zone's top-left corner as `(x, y)`."""
        return (self.x, self.y)

    @property
    def size(self) -> tuple[int, int]:
        """Return the zone's `(width, height)`."""
        return (self.width, self.height)

    @property
    def area(self) -> int:
        """Return the zone's area in pixels (`width * height`)."""
        return self.width * self.height

    @property
    def x0(self) -> int:
        """Return the inclusive left edge (`self.x`)."""
        return self.x

    @property
    def y0(self) -> int:
        """Return the inclusive top edge (`self.y`)."""
        return self.y

    @property
    def x1_inclusive(self) -> int:
        """Return the inclusive right edge (`self.x + self.width - 1`)."""
        return self.x + self.width - 1

    @property
    def y1_inclusive(self) -> int:
        """Return the inclusive bottom edge (`self.y + self.height - 1`)."""
        return self.y + self.height - 1

    @property
    def x1_exclusive(self) -> int:
        """Return the exclusive right edge (`self.x + self.width`)."""
        return self.x + self.width

    @property
    def y1_exclusive(self) -> int:
        """Return the exclusive bottom edge (`self.y + self.height`)."""
        return self.y + self.height

    @property
    def bbox_inclusive(self) -> tuple[int, int, int, int]:
        """
        Return a Pillow-style bbox `(x0, y0, x1, y1)` using inclusive ends.

        This matches how `layout.display_zone_overlay()` currently draws boxes:
        it uses `x1 = x0 + width - 1` and `y1 = y0 + height - 1`.
        """
        return (self.x0, self.y0, self.x1_inclusive, self.y1_inclusive)

    @property
    def bbox_exclusive(self) -> tuple[int, int, int, int]:
        """
        Return a bbox `(x0, y0, x1, y1)` using exclusive ends.

        Useful when you want width/height to line up with slicing semantics
        where the end coordinate is not included.
        """
        return (self.x0, self.y0, self.x1_exclusive, self.y1_exclusive)

    # ------------------------------------------------------------------
    # Corner points
    # ------------------------------------------------------------------

    @property
    def top_right(self) -> tuple[int, int]:
        """Return the zone's top-right corner (inclusive pixel coord)."""
        return (self.x1_inclusive, self.y0)

    @property
    def bottom_left(self) -> tuple[int, int]:
        """Return the zone's bottom-left corner (inclusive pixel coord)."""
        return (self.x0, self.y1_inclusive)

    @property
    def bottom_right(self) -> tuple[int, int]:
        """Return the zone's bottom-right corner (inclusive pixel coord)."""
        return (self.x1_inclusive, self.y1_inclusive)

    # ------------------------------------------------------------------
    # Percent/ratio -> pixel conversions
    # ------------------------------------------------------------------

    def width_ratio(self, ratio: float) -> float:
        """
        Convert a ratio (0..1) into a float pixel width for this zone.

        Example: if `width=200`, `width_ratio(0.5)` returns `100.0`.
        """
        return self.width * ratio

    def height_ratio(self, ratio: float) -> float:
        """Convert a ratio (0..1) into a float pixel height for this zone."""
        return self.height * ratio

    def width_percent(self, percent: float) -> float:
        """Convert a percent (0..100) into a float pixel width for this zone."""
        return self.width * (percent / 100)

    def height_percent(self, percent: float) -> float:
        """Convert a percent (0..100) into a float pixel height for this zone."""
        return self.height * (percent / 100)

    def width_ratio_int(self, ratio: float) -> int:
        """Integer version of `width_ratio()` using `round()`."""
        return int(round(self.width_ratio(ratio)))

    def height_ratio_int(self, ratio: float) -> int:
        """Integer version of `height_ratio()` using `round()`."""
        return int(round(self.height_ratio(ratio)))

    def width_percent_int(self, percent: float) -> int:
        """Integer version of `width_percent()` using `round()`."""
        return int(round(self.width_percent(percent)))

    def height_percent_int(self, percent: float) -> int:
        """Integer version of `height_percent()` using `round()`."""
        return int(round(self.height_percent(percent)))

    def point_at_ratio(self, x_ratio: float, y_ratio: float) -> tuple[float, float]:
        """
        Convert a normalized point (x_ratio, y_ratio) into global pixel coords.

        - `(0,0)` maps to the zone's top-left corner (`(x, y)`).
        - `(1,1)` maps to the zone's bottom-right corner *edge* (float),
          i.e. it may land on `x + width` / `y + height`.
        """
        return (self.x + self.width * x_ratio, self.y + self.height * y_ratio)

    def point_at_percent(self, x_percent: float, y_percent: float) -> tuple[float, float]:
        """Percent variant of `point_at_ratio()` (percent 0..100)."""
        return self.point_at_ratio(x_percent / 100, y_percent / 100)

    def point_at_ratio_int(self, x_ratio: float, y_ratio: float) -> tuple[int, int]:
        """Integer version of `point_at_ratio()` using `round()`."""
        px, py = self.point_at_ratio(x_ratio, y_ratio)
        return (int(round(px)), int(round(py)))

    def point_at_percent_int(self, x_percent: float, y_percent: float) -> tuple[int, int]:
        """Integer version of `point_at_percent()` using `round()`."""
        px, py = self.point_at_percent(x_percent, y_percent)
        return (int(round(px)), int(round(py)))

    # ------------------------------------------------------------------
    # Pixel -> percent/ratio conversions (reverse mapping)
    # ------------------------------------------------------------------

    def x_ratio(self, x_global: float) -> float:
        """
        Convert a global x coordinate into a ratio within this zone.

        Returns `(x_global - x) / width`. If `x_global` is outside the zone,
        the ratio will be outside 0..1.
        """
        if self.width == 0:
            return 0.0
        return (x_global - self.x) / self.width

    def y_ratio(self, y_global: float) -> float:
        """Convert a global y coordinate into a ratio within this zone."""
        if self.height == 0:
            return 0.0
        return (y_global - self.y) / self.height

    def x_percent(self, x_global: float) -> float:
        """Convert a global x coordinate into a percent within this zone."""
        return self.x_ratio(x_global) * 100

    def y_percent(self, y_global: float) -> float:
        """Convert a global y coordinate into a percent within this zone."""
        return self.y_ratio(y_global) * 100

    # ------------------------------------------------------------------
    # Local/global coordinate transforms
    # ------------------------------------------------------------------

    def local_to_global(self, local_x: float, local_y: float) -> tuple[float, float]:
        """Convert a local coordinate (relative to zone top-left) to global pixels."""
        return (self.x + local_x, self.y + local_y)

    def global_to_local(self, x_global: float, y_global: float) -> tuple[float, float]:
        """Convert global pixels into local coordinates relative to zone top-left."""
        return (x_global - self.x, y_global - self.y)

    # ------------------------------------------------------------------
    # Derived zones
    # ------------------------------------------------------------------

    def inset(self, padding: int) -> "Zone":
        """
        Return a new zone inset by `padding` pixels on all sides.

        If `padding` reduces the zone below zero size, the resulting width/height
        are clamped to 0.
        """
        new_w = self.width - (2 * padding)
        new_h = self.height - (2 * padding)
        return Zone(
            x=self.x + padding,
            y=self.y + padding,
            width=max(0, new_w),
            height=max(0, new_h),
        )


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
