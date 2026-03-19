"""Pokemon plugin – shows a random Pokémon from PokeAPI."""

from __future__ import annotations

import json
import random
import urllib.request
from io import BytesIO

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
        }
        return PluginData(payload=payload)

    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        draw = ImageDraw.Draw(image)
        fill = 0

        name_font = load_font(
            self.config, self.config.get("name_font", "Merriweather"), int(self.config.get("name_font_size", 28))
        )
        details_font = load_font(
            self.config, self.config.get("details_font", "Merriweather"), int(self.config.get("details_font_size", 16))
        )

        if data.error:
            draw.text((10, 10), "Pokémon unavailable", font=details_font, fill=fill)
            return

        p = data.payload or {}
        name = str(p.get("name", "")).strip()
        pid = p.get("id", "")
        types = p.get("types") or []
        types_str = ", ".join(str(t) for t in types) if types else "unknown"

        # Layout: optional sprite (20% height, 5% from top), then centered text
        # below it. Coordinates are local to `image` (zone_img), where (0,0)
        # is the zone top-left.
        sprite_bytes = p.get("sprite_bytes")
        sprite_h = 0
        sprite_top_y = zone.height_percent_int(5)

        def _draw_centered_text(text: str, *, font, y: int) -> int:
            """Draw `text` centered horizontally. Returns the text height."""
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            x = int(round((zone.width - tw) / 2))
            draw.text((x, y), text, font=font, fill=fill)
            return th

        if sprite_bytes and bool(self.config.get("show_sprite", True)):
            try:
                sprite = Image.open(BytesIO(sprite_bytes)).convert("RGBA")

                # Sprite is 20% of zone height (keep aspect ratio).
                target_h = max(1, zone.height_ratio_int(0.50))
                scale = target_h / max(1, sprite.height)
                target_w = int(round(sprite.width * scale))

                # Clamp to zone width.
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
            except Exception:
                sprite_h = 0

        gap = max(2, zone.height_percent_int(2))
        y_cursor = (sprite_top_y + sprite_h + gap) if sprite_h else zone.height_percent_int(5)

        title = f"#{pid} {name.capitalize() if name else name}"
        y_cursor += _draw_centered_text(title, font=name_font, y=y_cursor) + gap

        types_h = _draw_centered_text(f"Type: {types_str}", font=details_font, y=y_cursor)
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
            _draw_centered_text("  ".join(extra), font=details_font, y=y_cursor)
