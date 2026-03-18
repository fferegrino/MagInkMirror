"""
Font loading helpers.

Plugins should not hardcode OS-specific font paths. Instead they can request a
font by filename/path via config and fall back to PIL's default.
"""

from __future__ import annotations

import logging
from importlib.resources import as_file, files
from pathlib import Path

from PIL import ImageFont

log = logging.getLogger(__name__)


def _resolve_font_root(config: dict) -> Path | object:
    fonts_cfg = config.get("fonts", {}) if isinstance(config, dict) else {}
    d = fonts_cfg.get("dir", fonts_cfg.get("path", ".fonts"))

    if isinstance(d, str):
        # Special value: load fonts shipped inside the Python package.
        # Example: fonts.path = "@package:contrib/fonts"
        if d.startswith("@package:"):
            rel = d[len("@package:") :].lstrip("/")
            return files("maginkmirror").joinpath(rel)
        if d.startswith("package:"):
            rel = d[len("package:") :].lstrip("/")
            return files("maginkmirror").joinpath(rel)

    # Default: treat as a filesystem directory.
    return Path(d)


def _candidate_font_names(font: str) -> list[str]:
    """
    Expand a font spec into candidate filenames.

    If the user provides "Merriweather" (no extension) we try common extensions.
    If they provide a filename/path with an extension we try it as-is.
    """
    if Path(font).suffix:
        return [font]
    return [font, f"{font}.ttf", f"{font}.otf"]


def _try_load_truetype(path: str | Path, size: int):
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        return None


def _try_load_from_package(font_root: object, candidate_name: str, size: int):
    # `font_root` can be a Traversable (from importlib.resources). We keep the
    # implementation duck-typed by attempting `/` and `as_file`.
    try:
        resource_candidate = font_root / candidate_name  # type: ignore[operator]
    except Exception:
        return None

    try:
        with as_file(resource_candidate) as cand_path:
            if cand_path.exists():
                return _try_load_truetype(cand_path, size)
    except Exception as exc:
        log.debug("Failed to load package font %s: %s", resource_candidate, exc)
        return None
    return None


def _filesystem_candidates(font_root: object, candidate_name: str) -> list[Path]:
    candidates = [Path(candidate_name)]
    try:
        candidates.append(Path(font_root) / candidate_name)  # type: ignore[arg-type]
    except Exception:
        # font_root might be a package Traversable (or otherwise not a Path-like)
        log.warning(f"Font root is not a Path-like: {font_root}")
    return candidates


def load_font(config: dict, font: str | None, size: int):
    """
    Load a font with best-effort fallbacks.

    - If `font` is an absolute/relative path and exists, use it.
    - Else try `{fonts.dir}/{font}` when configured.
    - Else fall back to PIL default font.
    """
    if not font:
        return ImageFont.load_default()

    font_root = _resolve_font_root(config)

    for candidate_name in _candidate_font_names(font):
        loaded = _try_load_from_package(font_root, candidate_name, size)
        if loaded is not None:
            return loaded

        for cand in _filesystem_candidates(font_root, candidate_name):
            if not cand.exists():
                continue
            loaded = _try_load_truetype(cand, size)
            if loaded is not None:
                return loaded

    # Last-ditch: let PIL resolve by name (may work on some systems)
    loaded = _try_load_truetype(font, size)
    if loaded is not None:
        return loaded

    log.warning("Failed to load font %r (size=%s). Using default font.", font, size)
    return ImageFont.load_default()
