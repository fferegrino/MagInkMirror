"""Display adapters – abstract interface plus a headless implementation for dev."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)


class BaseDisplayAdapter(ABC):
    """
    Implement this to support a new e-ink hardware model.

    display() is called after every render cycle.  The adapter should
    decide whether to issue a full or partial refresh based on
    `dirty_plugins` and its own refresh-count heuristics.
    """

    @abstractmethod
    def display(self, image: Image.Image, dirty_plugins: set[str]) -> None:
        """Push `image` to the display."""

    @abstractmethod
    def clear(self) -> None:
        """Clear (white-out) the display."""

    @abstractmethod
    def close(self) -> None:
        """Release hardware resources."""


# ---------------------------------------------------------------------------
# Headless / development adapter
# ---------------------------------------------------------------------------


class HeadlessAdapter(BaseDisplayAdapter):
    """
    Saves each frame as a PNG to `output_dir`.

    No hardware required. Useful for CI, layout debugging, and screenshot generation.
    """

    def __init__(self, output_dir: str = "/tmp/inkmirror_output") -> None:
        self._out = Path(output_dir)
        self._out.mkdir(parents=True, exist_ok=True)
        self._frame = 0
        log.info("HeadlessAdapter: output → %s", self._out)

    def display(self, image: Image.Image, dirty_plugins: set[str]) -> None:
        """Save the image to the output directory."""
        fname = self._out / f"frame_{self._frame:04d}.png"
        image.convert("RGB").save(fname)
        log.info("Frame %04d saved (%s dirty)", self._frame, dirty_plugins)
        self._frame += 1

    def clear(self) -> None:
        """Clear the display."""
        log.debug("HeadlessAdapter: clear")

    def close(self) -> None:
        """Close the display."""
        log.debug("HeadlessAdapter: close")


# ---------------------------------------------------------------------------
# Waveshare stub – fill in with the actual waveshare_epd library calls
# ---------------------------------------------------------------------------


class WaveshareAdapter(BaseDisplayAdapter):
    """
    Stub for Waveshare HAT displays (e.g. 7.5" V2).

    Install the vendor library::

        pip install waveshare-epaper

    Then replace the stubs below with real calls.
    """

    #: How many partial refreshes before forcing a full refresh to clear ghosting.
    FULL_REFRESH_EVERY = 10

    def __init__(self, model: str = "epd7in5_V2") -> None:
        try:
            import importlib

            epd_module = importlib.import_module(f"waveshare_epd.{model}")
            self._epd = epd_module.EPD()
            self._epd.init()
        except ImportError as import_error:
            raise RuntimeError("waveshare-epaper not installed.  Run: pip install waveshare-epaper") from import_error
        self._partial_count = 0

    def display(self, image: Image.Image, dirty_plugins: set[str]) -> None:
        """Display the image on the display."""
        self._partial_count += 1
        if self._partial_count >= self.FULL_REFRESH_EVERY:
            log.info("Full e-ink refresh (ghosting prevention)")
            self._epd.init()
            self._epd.display(self._epd.getbuffer(image))
            self._partial_count = 0
        else:
            # Partial refresh where supported
            try:
                self._epd.displayPartial(self._epd.getbuffer(image))
            except AttributeError:
                self._epd.display(self._epd.getbuffer(image))

    def clear(self) -> None:
        """Clear the display."""
        self._epd.Clear()

    def close(self) -> None:
        """Close the display."""
        self._epd.sleep()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_adapter(config: dict) -> BaseDisplayAdapter:
    """Create a display adapter based on the configuration."""
    driver = config.get("display", {}).get("driver", "headless")
    if driver == "headless":
        out = config.get("display", {}).get("output_dir", "/tmp/maginkmirror_output")
        return HeadlessAdapter(output_dir=out)
    elif driver == "waveshare":
        model = config.get("display", {}).get("model", "epd7in5_V2")
        return WaveshareAdapter(model=model)
    else:
        raise ValueError(f"Unknown display driver: {driver!r}")
