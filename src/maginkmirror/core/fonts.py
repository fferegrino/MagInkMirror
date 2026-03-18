"""
Font loading helpers.

Plugins should not hardcode OS-specific font paths. Instead they can request a
font by filename/path via config and fall back to PIL's default.
"""

from __future__ import annotations

import logging
from pathlib import Path
from importlib.resources import as_file, files

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


def load_font(config: dict, font: str | None, size: int):
    """
    Load a font with best-effort fallbacks.

    - If `font` is an absolute/relative path and exists, use it.
    - Else try `{fonts.dir}/{font}` when configured.
    - Else fall back to PIL default font.
    """
    if not font:
        return ImageFont.load_default()

    # Allow config to specify a basename like "Merriweather" (no extension).
    font_names: list[str]
    font_path = Path(font)
    if font_path.suffix:
        font_names = [font]
    else:
        font_names = [font, f"{font}.ttf", f"{font}.otf"]

    font_root = _resolve_font_root(config)

    for candidate_name in font_names:
        candidates: list[Path] = []
        p = Path(candidate_name)
        candidates.append(p)

        # If font_root is a package resource, join it as a Traversable.
        resource_candidate = None
        try:
            resource_candidate = font_root / candidate_name  # type: ignore[operator]
        except Exception:
            resource_candidate = None

        if resource_candidate is not None:
            # Probe via a temp filesystem path if needed.
            try:
                with as_file(resource_candidate) as cand_path:
                    if cand_path.exists():
                        return ImageFont.truetype(str(cand_path), size)
                        log.info(f"Loaded font {cand_path} at size {size}")
            except Exception as exc:
                log.debug("Failed to load package font %s: %s", resource_candidate, exc)

        try:
            # filesystem directory
            candidates.append(Path(font_root) / candidate_name)  # type: ignore[arg-type]
        except Exception:
            pass

        for cand in candidates:
            try:
                if cand.exists():
                    return ImageFont.truetype(str(cand), size)
            except Exception as exc:
                log.debug("Failed to load font %s: %s", cand, exc)

    # Last-ditch: let PIL resolve by name (may work on some systems)
    try:
        return ImageFont.truetype(font, size)
    except Exception:
        return ImageFont.load_default()
