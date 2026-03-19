"""
SVG rendering + caching helpers.

MagInkMirror ultimately renders to Pillow images, so SVGs must be
rasterized before compositing.

This module provides a small API for plugins to:
  1. Load an SVG asset (filesystem path, or @package:... resource)
  2. Rasterize it into a Pillow image at the requested size
  3. Cache the raster output on disk so rendering happens once
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import shutil
import subprocess
from importlib.resources import as_file, files
from pathlib import Path
from typing import Literal

from PIL import Image

log = logging.getLogger(__name__)


SVGMode = Literal["RGBA", "RGB", "L", "1", "P"]


def _resolve_svg_asset(svg_spec: str | Path) -> tuple[bytes, str]:
    """
    Resolve an SVG spec into bytes.

    Supported:
      - filesystem path: `Path(...)` or `"/tmp/foo.svg"`
      - package resource: `"@package:contrib/icons/foo.svg"`
      - inline SVG markup: string starting with `<svg`
    """
    if isinstance(svg_spec, Path):
        b = svg_spec.read_bytes()
        return b, str(svg_spec)

    spec = str(svg_spec)
    s = spec.lstrip()
    if s.startswith("<svg"):
        return spec.encode("utf-8"), "inline-svg"

    if spec.startswith("@package:") or spec.startswith("package:"):
        rel = spec.split(":", 1)[1].lstrip("/")
        # maginkmirror is the root package that contains our package resources.
        traversable = files("maginkmirror").joinpath(rel)
        with as_file(traversable) as p:
            return Path(p).read_bytes(), spec

    p = Path(spec)
    return p.read_bytes(), spec


def _cache_path(*, cache_dir: Path, svg_bytes: bytes, width: int, height: int, mode: str) -> Path:
    h = hashlib.sha256(svg_bytes).hexdigest()
    name = f"svg_{h[:16]}_{width}x{height}_{mode}.png"
    return cache_dir / name


def _ensure_cache_dir(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)


def _render_svg_png(svg_bytes: bytes, width: int, height: int, *, background_color: str | None) -> bytes:
    """
    Render SVG bytes into a PNG (bytes) using the best available backend.

    Backends tried (in order):
      1. `cairosvg` Python package (if installed)
      2. `rsvg-convert` command (if available on PATH)
    """
    # 1) cairosvg
    try:
        import cairosvg  # type: ignore[import-not-found]

        kwargs: dict[str, object] = {
            "bytestring": svg_bytes,
            "output_width": width,
            "output_height": height,
        }
        if background_color:
            # cairosvg uses CSS-style colors, e.g. "#ffffff".
            kwargs["background_color"] = background_color

        return cairosvg.svg2png(**kwargs)  # type: ignore[arg-type]
    except ModuleNotFoundError:
        log.warning("cairosvg not installed, trying fallback")
    except Exception as exc:
        log.warning("cairosvg render failed, trying fallback: %s", exc)

    # 2) rsvg-convert
    if shutil.which("rsvg-convert") is None:
        raise RuntimeError("No SVG renderer available. Install `cairosvg` or ensure `rsvg-convert` is installed.")

    cmd = ["rsvg-convert", "-w", str(width), "-h", str(height)]
    if background_color:
        cmd.extend(["--background-color", background_color])

    proc = subprocess.run(
        cmd,
        input=svg_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"rsvg-convert failed: rc={proc.returncode} stderr={proc.stderr.decode('utf-8', 'ignore')}")

    return proc.stdout


def render_svg_to_image(
    svg_spec: str | Path,
    *,
    width: int,
    height: int,
    mode: str = "RGBA",
    cache_dir: str | Path | None = None,
    background_color: str | None = None,
) -> Image.Image:
    """
    Rasterize `svg_spec` to a Pillow image of `(width, height)`.

    The result is cached on disk to avoid repeated SVG rasterization.

    Parameters
    ----------
    - `svg_spec`: filesystem path, `"@package:..."` resource, or inline SVG markup
    - `mode`: Pillow mode to return (e.g. `"RGB"`, `"RGBA"`, `"L"`, `"1"`)
    - `cache_dir`: where to store cached PNGs (defaults to `.maginkmirror/cache/svg`)
    - `background_color`: optional renderer background color (often needed to avoid
      transparency issues, depending on mode/renderer)

    """
    svg_bytes, _source = _resolve_svg_asset(svg_spec)

    if cache_dir is None:
        cache_dir = Path(".maginkmirror") / "cache" / "svg"
    cache_dir_p = Path(cache_dir)
    _ensure_cache_dir(cache_dir_p)

    cached_png = _cache_path(cache_dir=cache_dir_p, svg_bytes=svg_bytes, width=width, height=height, mode=mode)
    if cached_png.exists():
        img = Image.open(cached_png)
        return img.convert(mode)

    png_bytes = _render_svg_png(svg_bytes, width, height, background_color=background_color)

    img = Image.open(io.BytesIO(png_bytes))
    img = img.convert("RGBA").resize((width, height))
    img = img.convert(mode)

    tmp = cached_png.with_suffix(".tmp.png")
    img.save(tmp)
    os.replace(tmp, cached_png)
    return img
