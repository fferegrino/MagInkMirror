import logging

from PIL import Image

from maginkmirror.display.base_display_adapter import BaseDisplayAdapter

log = logging.getLogger(__name__)


class InkyImpressionAdapter(BaseDisplayAdapter):
    """Adapter for the Inky Impression display."""

    FULL_REFRESH_EVERY = 10

    def __init__(self, model: str = "auto") -> None:
        self._partial_count = 0
        try:
            import inky as inky_module
            from inky.auto import auto

            self._display = auto()

            self._inky = inky_module

            log.info(f"Inky Impression display initialized: {self._display.resolution}")
            log.info(f"Inky Impression display color: {self._display.colour}")
        except ImportError as import_error:
            raise RuntimeError("inky not installed.  Run: pip install inky") from import_error
        except Exception as e:
            raise RuntimeError("Failed to initialize Inky Impression display") from e

    def display(self, image: Image.Image, dirty_plugins: set[str]) -> None:
        """Display the image on the Inky Impression display."""
        log.info(f"Displaying image on Inky Impression display: {image.size}")
        log.info(f"Image mode: {image.mode}")
        log.info(f"Image format: {image.format}")
        log.info(f"Image width: {image.width}")
        log.info(f"Image height: {image.height}")
        # self._display.set_image(image)
        self._display.set_border(self._inky.BLACK)

        self._display.show()

    def clear(self) -> None:
        """Clear the display."""

    def close(self) -> None:
        """Close the display."""
