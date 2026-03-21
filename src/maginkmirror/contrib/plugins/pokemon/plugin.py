"""Pokemon plugin – shows a random Pokémon from PokeAPI."""

from __future__ import annotations

import json
import random
import urllib.request
from io import BytesIO

from colour import Color
from PIL import Image, ImageDraw

from maginkmirror.core.fonts import load_font
from maginkmirror.plugins import BasePlugin, PluginData, Zone

PLUGIN_CLASS = "PokemonPlugin"

_DEFAULT_HEADERS = {
    # Some endpoints reject requests without a UA.
    "User-Agent": "MagInkMirror/1.0 (+https://github.com/antonioferegrino/MagInkMirror)",
    "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
}


def _urlopen_with_headers(url: str, *, timeout: int = 10):
    req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
    return urllib.request.urlopen(req, timeout=timeout)


TYPE_COLORS = {
    "normal": Color("#A8A878"),
    "fire": Color("#F08030"),
    "water": Color("#6890F0"),
    "electric": Color("#F8D030"),
    "grass": Color("#78C850"),
    "ice": Color("#98D8D8"),
    "fighting": Color("#C03028"),
    "poison": Color("#A040A0"),
    "ground": Color("#E0C068"),
    "flying": Color("#A890F0"),
    "psychic": Color("#F85888"),
    "bug": Color("#A8B820"),
    "rock": Color("#B8A038"),
    "ghost": Color("#705898"),
    "dragon": Color("#7038F8"),
    "dark": Color("#705848"),
    "steel": Color("#B8B8D0"),
    "fairy": Color("#EE99AC"),
}

_LIGHT_BG_LUM_THRESHOLD = 0.55

# Ascenders + descenders; stabilizes textbbox line metrics (same idea as CSS line-height).
_REFERENCE_LINE_TEXT = "gjylth"


def _reference_bbox(draw, font) -> tuple[int, int, int, int]:
    """One textbbox per font per frame — use for stable line height and y advance."""
    return draw.textbbox((0, 0), _REFERENCE_LINE_TEXT, font=font)


def _darken(color: Color, amount: float) -> Color:
    """Linear blend toward black. ``amount`` in 0..1 (0 = unchanged, 1 = black)."""
    amount = max(0.0, min(1.0, amount))
    r, g, b = color.get_rgb()
    r *= 1.0 - amount
    g *= 1.0 - amount
    b *= 1.0 - amount
    out = Color()
    out.set_rgb((r, g, b))
    return out


def _lighten(color: Color, amount: float) -> Color:
    """Linear blend toward white. ``amount`` in 0..1 (0 = unchanged, 1 = white)."""
    amount = max(0.0, min(1.0, amount))
    r, g, b = color.get_rgb()
    r = r + (1.0 - r) * amount
    g = g + (1.0 - g) * amount
    b = b + (1.0 - b) * amount
    out = Color()
    out.set_rgb((r, g, b))
    return out


def _color_rgb_u8(color: Color) -> tuple[int, int, int]:
    r, g, b = color.get_rgb()
    return (int(r * 255), int(g * 255), int(b * 255))


def _type_fill_rgb(type_name: str) -> tuple[int, int, int]:
    c = TYPE_COLORS.get(type_name.lower())
    if c is None:
        c = Color("#888888")
    rgb = c.get_rgb()
    return (int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))


def _text_fill_for_bg(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    r, g, b = bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return (20, 20, 20) if luminance > _LIGHT_BG_LUM_THRESHOLD else (255, 255, 255)


def _draw_types_row(
    draw,
    zone: Zone,
    y: int,
    types: list,
    *,
    font,
    ref_bbox: tuple[int, int, int, int],
) -> int:
    """Draw one rounded box per type. Returns row height."""
    display = [str(t) for t in types] if types else ["unknown"]
    pad_x = max(4, zone.width // 80)
    pad_y = max(3, zone.height // 120)
    gap = max(6, zone.width // 60)

    line_h = ref_bbox[3] - ref_bbox[1]

    box_items: list[tuple[str, str, tuple, int, int]] = []
    for t in display:
        key = str(t).lower()
        text = str(t).capitalize()
        tb = draw.textbbox((0, 0), text, font=font)
        tw = tb[2] - tb[0]
        box_items.append((text, key, tb, tw, line_h))

    uniform_box_h = line_h + 2 * pad_y
    row_h = uniform_box_h

    total_w = sum(tw + 2 * pad_x for _t, _k, _tb, tw, _th in box_items) + gap * max(0, len(box_items) - 1)

    start_x = int(round((zone.width - total_w) / 2))
    cx = start_x

    for text, key, tb, tw, th in box_items:
        box_w = tw + 2 * pad_x
        box_h = uniform_box_h
        bg = _type_fill_rgb(key)
        tfill = _text_fill_for_bg(bg)
        box_y = y
        r = min(4, max(1, box_h // 4))
        draw.rounded_rectangle((cx, box_y, cx + box_w, box_y + box_h), radius=r, fill=bg)
        tx = cx + pad_x - tb[0]
        ty = box_y + (box_h - th) // 2 - ref_bbox[1] + 1
        draw.text((tx, ty), text, font=font, fill=tfill)
        cx += box_w + gap

    return row_h


def _draw_centered_text(
    draw,
    zone: Zone,
    text: str,
    *,
    font,
    y: int,
    fill: tuple[int, int, int],
    ref_bbox: tuple[int, int, int, int],
) -> int:
    """Center horizontally; vertically center string in reference line; return ref line height."""
    tb = draw.textbbox((0, 0), text, font=font)
    tw = tb[2] - tb[0]
    text_h = tb[3] - tb[1]
    line_h = ref_bbox[3] - ref_bbox[1]
    x = int(round((zone.width - tw) / 2))
    ty = y + (line_h - text_h) // 2 - tb[1]
    draw.text((x, ty), text, font=font, fill=fill)
    return line_h


def _paste_sprite_zone(image: Image.Image, zone: Zone, sprite_bytes: bytes) -> tuple[int, int]:
    """Paste the sprite into the zone; returns (height, top_y). Height is 0 on failure."""
    sprite_top_y = zone.height_percent_int(0)
    try:
        sprite = Image.open(BytesIO(sprite_bytes)).convert("RGBA")
        target_h = max(1, zone.height_ratio_int(0.50))
        scale = target_h / max(1, sprite.height)
        target_w = int(round(sprite.width * scale))
        if target_w > max(1, zone.width):
            scale = zone.width / max(1, sprite.width)
            target_w = max(1, zone.width)
            target_h = int(round(sprite.height * scale))
        sprite_h = target_h
        sprite_top_y = min(sprite_top_y, max(0, zone.height - sprite_h))
        sprite_left_x = max(0, (zone.width - target_w) // 2)
        sprite = sprite.resize((target_w, sprite_h))
        sprite_l = sprite.convert(image.mode)
        image.paste(sprite_l, (sprite_left_x, sprite_top_y), mask=sprite.split()[-1])
        return sprite_h, sprite_top_y
    except Exception:
        return 0, sprite_top_y


class PokemonPlugin(BasePlugin):
    """
    Pokemon plugin – fetches a random Pokémon from PokeAPI.

    Config (all optional) under `[plugins.pokemon]`:
    - max_id: int (default 1025)
    - show_sprite: bool (default true)
    - name_font / name_font_size
    - details_font / details_font_size
    """

    name = "pokemon"
    interval = 60  # every minute

    def fetch(self) -> PluginData:
        """Fetch a random Pokémon from PokeAPI."""
        max_id = int(self.config.get("max_id", 1025))
        max_id = max(1, max_id)
        poke_id = random.randint(1, max_id)

        url = f"https://pokeapi.co/api/v2/pokemon/{poke_id}"
        with _urlopen_with_headers(url, timeout=10) as resp:
            body = json.loads(resp.read())

        types = [t["type"]["name"] for t in body.get("types", []) if "type" in t]
        sprite_url = body.get("sprites", {}).get("front_default") or body.get("sprites", {}).get("other", {}).get(
            "official-artwork", {}
        ).get("front_default")

        species_url = body.get("species", {}).get("url")
        if species_url:
            with _urlopen_with_headers(species_url, timeout=10) as resp:
                species_body = json.loads(resp.read())
                color = species_body.get("color", {}).get("name")
        else:
            color = None

        sprite_bytes: bytes | None = None
        if sprite_url and bool(self.config.get("show_sprite", True)):
            try:
                with _urlopen_with_headers(sprite_url, timeout=10) as img_resp:
                    sprite_bytes = img_resp.read()
            except Exception:
                sprite_bytes = None

        payload = {
            "id": body.get("id", poke_id),
            "name": body.get("name", f"#{poke_id}"),
            "types": types,
            "height": body.get("height"),
            "weight": body.get("weight"),
            "sprite_bytes": sprite_bytes,
            "species_color": color,
        }
        return PluginData(payload=payload)

    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        """Draw name, types, and stats into the zone."""
        draw = ImageDraw.Draw(image)
        species_color = data.payload.get("species_color")
        species_color = "black" if species_color == "white" else species_color
        species_color = Color(species_color)
        text_fill = _color_rgb_u8(_darken(species_color, 0.4))
        background_fill = _color_rgb_u8(_lighten(species_color, 0.9))
        draw.rectangle((0, 0, zone.width, zone.height), fill=background_fill)

        name_font = load_font(
            self.config, self.config.get("name_font", "Merriweather"), int(self.config.get("name_font_size", 25))
        )
        details_font = load_font(
            self.config, self.config.get("details_font", "Merriweather"), int(self.config.get("details_font_size", 16))
        )

        if data.error:
            draw.text((10, 10), "Pokémon unavailable", font=details_font, fill=0)
            return

        p = data.payload or {}
        name = str(p.get("name", "")).strip()
        pid = p.get("id", "")
        types = p.get("types") or []

        # Layout: optional sprite (20% height, 5% from top), then centered text
        # below it. Coordinates are local to `image` (zone_img), where (0,0)
        # is the zone top-left.
        sprite_bytes = p.get("sprite_bytes")
        sprite_h = 0
        sprite_top_y = zone.height_percent_int(0)
        if sprite_bytes and bool(self.config.get("show_sprite", True)):
            sprite_h, sprite_top_y = _paste_sprite_zone(image, zone, sprite_bytes)

        gap = max(2, zone.height_percent_int(2))
        y_cursor = (sprite_top_y + sprite_h + gap) if sprite_h else zone.height_percent_int(5)

        ref_name = _reference_bbox(draw, name_font)
        ref_details = _reference_bbox(draw, details_font)

        title = f"#{pid} {name.capitalize() if name else name}"
        y_cursor += (
            _draw_centered_text(draw, zone, title, font=name_font, y=y_cursor, fill=text_fill, ref_bbox=ref_name) + gap
        )

        types_h = _draw_types_row(draw, zone, y_cursor, types, font=details_font, ref_bbox=ref_details)
        y_cursor += types_h + gap

        # Show height/weight when present (PokeAPI uses decimeters/hectograms).
        height_dm = p.get("height")
        weight_hg = p.get("weight")
        extra: list[str] = []
        if isinstance(height_dm, (int, float)):
            extra.append(f"H: {height_dm / 10:.1f}m")
        if isinstance(weight_hg, (int, float)):
            extra.append(f"W: {weight_hg / 10:.1f}kg")
        if extra:
            _draw_centered_text(
                draw, zone, "  ".join(extra), font=details_font, y=y_cursor, fill=text_fill, ref_bbox=ref_details
            )
