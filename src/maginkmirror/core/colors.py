"""Color utilities wrapping ``colour.Color`` for use across MagInkMirror."""

from __future__ import annotations

from typing import Any

from colour import Color as _Colour

# Relative luminance threshold for picking dark vs light foreground (sRGB).
_LIGHT_BG_LUM_THRESHOLD = 0.55


class Color:
    """
    Wraps ``colour.Color`` with chainable ``darken`` / ``lighten`` and 8-bit RGB for PIL.

    All other attributes and methods are delegated to the underlying ``colour.Color``
    (e.g. ``get_hex``, ``get_hsl``, ``hex``, ``set_hue``, ``range_to``, …).
    """

    __slots__ = ("_c",)

    def __init__(self, value: str | Color | _Colour | None = None):
        if isinstance(value, Color):
            self._c = _Colour()
            self._c.set_rgb(value._c.get_rgb())
        elif isinstance(value, _Colour):
            self._c = value
        else:
            self._c = _Colour(value)

    @classmethod
    def _from_colour(cls, c: _Colour) -> Color:
        inst = object.__new__(cls)
        inst._c = c
        return inst

    def darken(self, amount: float) -> Color:
        """Linear blend toward black. ``amount`` in 0..1 (0 = unchanged, 1 = black)."""
        amount = max(0.0, min(1.0, amount))
        r, g, b = self._c.get_rgb()
        r *= 1.0 - amount
        g *= 1.0 - amount
        b *= 1.0 - amount
        out = _Colour()
        out.set_rgb((r, g, b))
        return Color._from_colour(out)

    def lighten(self, amount: float) -> Color:
        """Linear blend toward white. ``amount`` in 0..1 (0 = unchanged, 1 = white)."""
        amount = max(0.0, min(1.0, amount))
        r, g, b = self._c.get_rgb()
        r = r + (1.0 - r) * amount
        g = g + (1.0 - g) * amount
        b = b + (1.0 - b) * amount
        out = _Colour()
        out.set_rgb((r, g, b))
        return Color._from_colour(out)

    def rgb_u8(self) -> tuple[int, int, int]:
        """PIL-style ``(R, G, B)`` with values 0–255."""
        r, g, b = self._c.get_rgb()
        return (int(r * 255), int(g * 255), int(b * 255))

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the underlying ``colour.Color``."""
        return getattr(self._c, name)

    def __eq__(self, other: object) -> bool:
        """Return whether ``other`` is a ``Color`` with the same RGB."""
        if not isinstance(other, Color):
            return NotImplemented
        return self._c.get_rgb() == other._c.get_rgb()

    def __hash__(self) -> int:
        """Hash from sRGB tuple (mutable underlying colour may still change)."""
        return hash(self._c.get_rgb())

    def __repr__(self) -> str:
        """Return ``Color('#abc')``-style debug representation."""
        return f"{self.__class__.__name__}({self._c.get_hex()!r})"


__all__ = ["Color", "contrasting_foreground_rgb"]


def contrasting_foreground_rgb(
    bg_rgb: tuple[int, int, int],
    *,
    light_bg_threshold: float = _LIGHT_BG_LUM_THRESHOLD,
) -> tuple[int, int, int]:
    """Dark or near-white text for readability on ``bg_rgb`` (sRGB, 0–255)."""
    r, g, b = bg_rgb[0] / 255.0, bg_rgb[1] / 255.0, bg_rgb[2] / 255.0
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return (20, 20, 20) if luminance > light_bg_threshold else (255, 255, 255)
