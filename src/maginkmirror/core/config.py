"""Configuration loading."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ENV_VAR_DEFAULT_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)\}")


def _interpolate_env(config_text: str, *, path: Path) -> str:
    """
    Perform basic environment variable interpolation.

    Supported forms:
    - `${VAR}`: must exist in the environment, otherwise raises.
    - `${VAR:-default}`: uses `default` when VAR is not set.

    Interpolation is done on raw config text before TOML parsing.
    """

    def _replace_default(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default_value = match.group(2)
        return os.environ.get(var_name, default_value)

    def _replace_required(match: re.Match[str]) -> str:
        var_name = match.group(1)
        if var_name not in os.environ:
            raise ValueError(f"Missing env var {var_name!r} referenced in config {path}")
        return os.environ[var_name]

    # Handle defaults first so we don't partially consume `${VAR:-...}`.
    config_text = _ENV_VAR_DEFAULT_RE.sub(_replace_default, config_text)
    config_text = _ENV_VAR_RE.sub(_replace_required, config_text)
    return config_text


def load_config(path: Path | str) -> dict:
    """Load the configuration from a file, with basic env interpolation."""
    config_path = Path(path)
    raw = config_path.read_text(encoding="utf-8")
    raw = _interpolate_env(raw, path=config_path)
    return tomllib.loads(raw)
