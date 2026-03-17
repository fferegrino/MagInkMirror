"""Configuration loading."""

import tomllib
from pathlib import Path


def load_config(path: Path) -> dict:
    """Load the configuration from a file."""
    with open(path, "rb") as f:
        return tomllib.load(f)
