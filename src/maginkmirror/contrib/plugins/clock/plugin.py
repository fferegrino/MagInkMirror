"""Clock plugin – renders the current time into its zone."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun
from colour import Color
from PIL import Image, ImageDraw

from maginkmirror.core.fonts import load_font
from maginkmirror.core.svg import render_svg_to_image
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
        fmt = self.config.get("format", "%H:%M:%S")
        return PluginData(
            payload={"time": now.strftime(fmt), "date": now.strftime("%A, %d %B %Y"), "timezone": tz_name}
        )

    def get_sun_intervals(self, date: datetime) -> list[datetime]:
        location = LocationInfo("London", "England", "Europe/London", 51.507351, -0.127758)
        begin_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        sun_over_location = sun(location.observer, date=date)

        return [
            begin_of_day,  # Need to add the beginning of the day
            sun_over_location["dawn"],
            sun_over_location["sunrise"],
            sun_over_location["noon"],
            sun_over_location["sunset"],
            sun_over_location["dusk"],
            begin_of_day + timedelta(days=1),  # Need to add the beginning of the next day
        ]

    def get_colors(self, date: datetime) -> tuple[Color, Color, Color]:
        sun_intervals = self.get_sun_intervals(date)
        darkness = Color("#5D5D5E")
        night = Color("#7f7f7f")
        mid = Color("#a2a2a2")
        noon = Color("#c7c7c7")
        black = Color("#000000")
        white = Color("#ffffff")

        if sun_intervals[0] <= date < sun_intervals[1]:
            log.info(f"First interval {date} {sun_intervals[0]} {sun_intervals[1]}")
            return darkness, night, white
        elif sun_intervals[1] <= date < sun_intervals[2]:
            log.info(f"Second interval {date} {sun_intervals[1]} {sun_intervals[2]}")
            return night, mid, white
        elif sun_intervals[2] <= date < sun_intervals[3]:
            log.info(f"Third interval {date} {sun_intervals[2]} {sun_intervals[3]}")
            return mid, noon, black
        elif sun_intervals[3] <= date < sun_intervals[4]:
            log.info(f"Fourth interval {date} {sun_intervals[3]} {sun_intervals[4]}")
            return noon, mid, black
        elif sun_intervals[4] <= date < sun_intervals[5]:
            log.info(f"Fifth interval {date} {sun_intervals[4]} {sun_intervals[5]}")
            return mid, night, white
        else:
            log.info(f"Sixth interval {date} {sun_intervals[5]} {sun_intervals[6]}")
            return night, darkness, white

    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        """Render the current time."""
        draw = ImageDraw.Draw(image)
        payload = data.payload

        time_font = load_font(self.config, self.config.get("time_font"), int(self.config.get("time_font_size", 24)))
        date_font = load_font(self.config, self.config.get("date_font"), int(self.config.get("date_font_size", 72)))

        top_color, bottom_color, fill_color = self.get_colors(datetime.now(tz=ZoneInfo(payload.get("timezone", "UTC"))))

        clock_svg = render_svg_to_image(
            "@package:contrib/plugins/clock/backgrounds/dusk.svg",
            width=zone.width,
            height=zone.height,
            template_vars={"top_color": top_color.hex, "bottom_color": bottom_color.hex},
        )
        image.paste(clock_svg, (0, 0))

        fill = fill_color.get_rgb()
        fill = (int(fill[0] * 255), int(fill[1] * 255), int(fill[2] * 255))

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
