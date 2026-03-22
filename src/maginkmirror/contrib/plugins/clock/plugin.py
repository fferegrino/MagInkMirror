"""Clock plugin – renders the current time into its zone."""

from __future__ import annotations

import logging
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from maginkmirror.core.fonts import load_font
from maginkmirror.plugins import BasePlugin, PluginData, Zone

PLUGIN_CLASS = "ClockPlugin"

log = logging.getLogger(__name__)


class ClockPlugin(BasePlugin):
    """Clock plugin – renders the current time into its zone."""

    name = "clock"
    interval = 30  # refresh every 30 seconds

    def fetch(self) -> PluginData:
        """Fetch the current time."""
        tz_name = self.config.get("timezone", "UTC")
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(tz_name)
        except Exception:
            tz = None  # fall back to local time

        now = datetime.now(tz=tz)
        fmt = self.config.get("time_format", "%H:%M:%S")
        date_fmt = self.config.get("date_format", "%A, %d %B %Y")
        return PluginData(payload={"time": now.strftime(fmt), "date": now.strftime(date_fmt), "timezone": tz_name})

    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        """Render the current time."""
        draw = ImageDraw.Draw(image)
        payload = data.payload

        main_font = load_font(self.config, self.config.get("main_font"), int(self.config.get("main_font_size", 60)))
        secondary_font = load_font(
            self.config, self.config.get("secondary_font"), int(self.config.get("secondary_font_size", 24))
        )

        fill = (0, 0, 0)

        main_key = (self.config.get("main_info") or "").strip()
        secondary_key = (self.config.get("secondary_info") or "").strip()

        main_text = str(payload.get(main_key, "")).strip() if main_key else ""
        secondary_text = str(payload.get(secondary_key, "")).strip() if secondary_key else ""

        lines: list[tuple[str, ImageFont.ImageFont]] = []
        if main_key and main_text:
            lines.append((main_text, main_font))
        if secondary_key and secondary_text:
            lines.append((secondary_text, secondary_font))

        if not lines:
            return

        gap = max(4, int(self.config.get("secondary_font_size", 24)) // 6)
        heights: list[int] = []
        for text, font in lines:
            bbox = draw.textbbox((0, 0), text, font=font)
            heights.append(bbox[3] - bbox[1])
        total_h = sum(heights) + gap * (len(lines) - 1)
        y = max(0, (zone.height - total_h) // 2)

        for i, ((text, font), h) in enumerate(zip(lines, heights, strict=True)):
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            x = (zone.width - tw) // 2
            draw.text((x, y), text, font=font, fill=fill)
            y += h + (gap if i < len(lines) - 1 else 0)
