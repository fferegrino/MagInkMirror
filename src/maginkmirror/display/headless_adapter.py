import logging
from pathlib import Path

from PIL import Image

from maginkmirror.display.base_display_adapter import BaseDisplayAdapter

log = logging.getLogger(__name__)


class HeadlessAdapter(BaseDisplayAdapter):
    """
    Saves each frame as a PNG to `output_dir`.

    No hardware required. Useful for CI, layout debugging, and screenshot generation.
    """

    def __init__(self, output_dir: str = "/tmp/inkmirror_output", preserve_color: bool = True) -> None:
        self._out = Path(output_dir)
        self._out.mkdir(parents=True, exist_ok=True)
        self._frame = 0
        self._preserve_color = preserve_color
        log.info("HeadlessAdapter: output → %s", self._out)

    def display(self, image: Image.Image, dirty_plugins: set[str]) -> None:
        """Save the image to the output directory."""
        fname = self._out / f"frame_{self._frame:04d}.png"
        if self._preserve_color:
            # Keep the rendered mode (RGB/RGBA/L/1) as-is.
            image.save(fname)
        else:
            image.convert("RGB").save(fname)
        log.info("Frame %04d saved (%s dirty)", self._frame, dirty_plugins)
        self._frame += 1

    def clear(self) -> None:
        """Clear the display."""
        log.debug("HeadlessAdapter: clear")

    def close(self) -> None:
        """Close the display."""
        log.debug("HeadlessAdapter: close")
