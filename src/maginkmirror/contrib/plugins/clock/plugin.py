"""Clock plugin – renders the current time into its zone."""

from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

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
        fmt = self.config.get("format", "%H:%M")
        return PluginData(payload={"time": now.strftime(fmt), "date": now.strftime("%A, %d %B %Y")})

    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        """Render the current time."""
        draw = ImageDraw.Draw(image)
        payload = data.payload

        # Try to load a nicer font; fall back to the PIL default
        try:
            time_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
            date_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except OSError:
            time_font = ImageFont.load_default()
            date_font = ImageFont.load_default()

        fill = 0  # black

        # Time – centred horizontally
        time_str = payload.get("time", "")
        bbox = draw.textbbox((0, 0), time_str, font=time_font)
        tw = bbox[2] - bbox[0]
        draw.text(((zone.width - tw) // 2, 10), time_str, font=time_font, fill=fill)

        # Date – centred below
        date_str = payload.get("date", "")
        bbox = draw.textbbox((0, 0), date_str, font=date_font)
        dw = bbox[2] - bbox[0]
        draw.text(((zone.width - dw) // 2, 90), date_str, font=date_font, fill=fill)
