"""Display adapters – abstract interface plus a headless implementation for dev."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

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
