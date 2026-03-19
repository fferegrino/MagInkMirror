"""Clock plugin – renders the current time into its zone."""

from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw

from maginkmirror.core.fonts import load_font
from maginkmirror.core.svg import render_svg_to_image
from maginkmirror.plugins import BasePlugin, PluginData, Zone

PLUGIN_CLASS = "ClockPlugin"


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
        fmt = self.config.get("format", "%H:%M:%S")
        return PluginData(payload={"time": now.strftime(fmt), "date": now.strftime("%A, %d %B %Y")})

    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        """Render the current time."""
        draw = ImageDraw.Draw(image)
        payload = data.payload

        time_font = load_font(self.config, self.config.get("time_font"), int(self.config.get("time_font_size", 24)))
        date_font = load_font(self.config, self.config.get("date_font"), int(self.config.get("date_font_size", 72)))

        clock_svg = render_svg_to_image(
            "@package:contrib/plugins/clock/backgrounds/dusk.svg", width=zone.width, height=zone.height
        )
        image.paste(clock_svg, (0, 0))

        fill = (255, 255, 255)

        # Time – centred horizontally
        date_str = payload.get("date", "")
        bbox = draw.textbbox((0, 0), date_str, font=date_font)
        tw = bbox[2] - bbox[0]
        draw.text(((zone.width - tw) // 2, 10), date_str, font=date_font, fill=fill)

        # Time – centred below
        time_str = payload.get("time", "")
        bbox = draw.textbbox((0, 0), time_str, font=time_font)
        dw = bbox[2] - bbox[0]
        draw.text(((zone.width - dw) // 2, 90), time_str, font=time_font, fill=fill)
