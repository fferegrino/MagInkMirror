"""Weather plugin – fetches current conditions from Open-Meteo (no key needed)."""

from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun
from PIL import Image, ImageDraw

from maginkmirror.core.fonts import load_font
from maginkmirror.plugins import BasePlugin, PluginData, Zone

PLUGIN_CLASS = "WeatherPlugin"

# When astral cannot compute sun times (polar edge cases), treat these local hours as "day".
_FALLBACK_DAY_START_HOUR = 6
_FALLBACK_DAY_END_HOUR = 20

_DEFAULT_HEADERS = {
    "User-Agent": "MagInkMirror/1.0 (+https://github.com/antonioferegrino/MagInkMirror)",
    "Accept": "image/png,image/*;q=0.9,*/*;q=0.8",
}

# WMO weather code → short label
WMO_CODES = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Showers",
    81: "Showers",
    82: "Heavy showers",
    95: "Thunderstorm",
    99: "Hail",
}

WEATHER_CODES = {
    "0": {
        "day": {"description": "Sunny", "image": "http://openweathermap.org/img/wn/01d@2x.png"},
        "night": {"description": "Clear", "image": "http://openweathermap.org/img/wn/01n@2x.png"},
    },
    "1": {
        "day": {"description": "Mainly Sunny", "image": "http://openweathermap.org/img/wn/01d@2x.png"},
        "night": {"description": "Mainly Clear", "image": "http://openweathermap.org/img/wn/01n@2x.png"},
    },
    "2": {
        "day": {"description": "Partly Cloudy", "image": "http://openweathermap.org/img/wn/02d@2x.png"},
        "night": {"description": "Partly Cloudy", "image": "http://openweathermap.org/img/wn/02n@2x.png"},
    },
    "3": {
        "day": {"description": "Cloudy", "image": "http://openweathermap.org/img/wn/03d@2x.png"},
        "night": {"description": "Cloudy", "image": "http://openweathermap.org/img/wn/03n@2x.png"},
    },
    "45": {
        "day": {"description": "Foggy", "image": "http://openweathermap.org/img/wn/50d@2x.png"},
        "night": {"description": "Foggy", "image": "http://openweathermap.org/img/wn/50n@2x.png"},
    },
    "48": {
        "day": {"description": "Rime Fog", "image": "http://openweathermap.org/img/wn/50d@2x.png"},
        "night": {"description": "Rime Fog", "image": "http://openweathermap.org/img/wn/50n@2x.png"},
    },
    "51": {
        "day": {"description": "Light Drizzle", "image": "http://openweathermap.org/img/wn/09d@2x.png"},
        "night": {"description": "Light Drizzle", "image": "http://openweathermap.org/img/wn/09n@2x.png"},
    },
    "53": {
        "day": {"description": "Drizzle", "image": "http://openweathermap.org/img/wn/09d@2x.png"},
        "night": {"description": "Drizzle", "image": "http://openweathermap.org/img/wn/09n@2x.png"},
    },
    "55": {
        "day": {"description": "Heavy Drizzle", "image": "http://openweathermap.org/img/wn/09d@2x.png"},
        "night": {"description": "Heavy Drizzle", "image": "http://openweathermap.org/img/wn/09n@2x.png"},
    },
    "56": {
        "day": {"description": "Light Freezing Drizzle", "image": "http://openweathermap.org/img/wn/09d@2x.png"},
        "night": {"description": "Light Freezing Drizzle", "image": "http://openweathermap.org/img/wn/09n@2x.png"},
    },
    "57": {
        "day": {"description": "Freezing Drizzle", "image": "http://openweathermap.org/img/wn/09d@2x.png"},
        "night": {"description": "Freezing Drizzle", "image": "http://openweathermap.org/img/wn/09n@2x.png"},
    },
    "61": {
        "day": {"description": "Light Rain", "image": "http://openweathermap.org/img/wn/10d@2x.png"},
        "night": {"description": "Light Rain", "image": "http://openweathermap.org/img/wn/10n@2x.png"},
    },
    "63": {
        "day": {"description": "Rain", "image": "http://openweathermap.org/img/wn/10d@2x.png"},
        "night": {"description": "Rain", "image": "http://openweathermap.org/img/wn/10n@2x.png"},
    },
    "65": {
        "day": {"description": "Heavy Rain", "image": "http://openweathermap.org/img/wn/10d@2x.png"},
        "night": {"description": "Heavy Rain", "image": "http://openweathermap.org/img/wn/10n@2x.png"},
    },
    "66": {
        "day": {"description": "Light Freezing Rain", "image": "http://openweathermap.org/img/wn/10d@2x.png"},
        "night": {"description": "Light Freezing Rain", "image": "http://openweathermap.org/img/wn/10n@2x.png"},
    },
    "67": {
        "day": {"description": "Freezing Rain", "image": "http://openweathermap.org/img/wn/10d@2x.png"},
        "night": {"description": "Freezing Rain", "image": "http://openweathermap.org/img/wn/10n@2x.png"},
    },
    "71": {
        "day": {"description": "Light Snow", "image": "http://openweathermap.org/img/wn/13d@2x.png"},
        "night": {"description": "Light Snow", "image": "http://openweathermap.org/img/wn/13n@2x.png"},
    },
    "73": {
        "day": {"description": "Snow", "image": "http://openweathermap.org/img/wn/13d@2x.png"},
        "night": {"description": "Snow", "image": "http://openweathermap.org/img/wn/13n@2x.png"},
    },
    "75": {
        "day": {"description": "Heavy Snow", "image": "http://openweathermap.org/img/wn/13d@2x.png"},
        "night": {"description": "Heavy Snow", "image": "http://openweathermap.org/img/wn/13n@2x.png"},
    },
    "77": {
        "day": {"description": "Snow Grains", "image": "http://openweathermap.org/img/wn/13d@2x.png"},
        "night": {"description": "Snow Grains", "image": "http://openweathermap.org/img/wn/13n@2x.png"},
    },
    "80": {
        "day": {"description": "Light Showers", "image": "http://openweathermap.org/img/wn/09d@2x.png"},
        "night": {"description": "Light Showers", "image": "http://openweathermap.org/img/wn/09n@2x.png"},
    },
    "81": {
        "day": {"description": "Showers", "image": "http://openweathermap.org/img/wn/09d@2x.png"},
        "night": {"description": "Showers", "image": "http://openweathermap.org/img/wn/09n@2x.png"},
    },
    "82": {
        "day": {"description": "Heavy Showers", "image": "http://openweathermap.org/img/wn/09d@2x.png"},
        "night": {"description": "Heavy Showers", "image": "http://openweathermap.org/img/wn/09n@2x.png"},
    },
    "85": {
        "day": {"description": "Light Snow Showers", "image": "http://openweathermap.org/img/wn/13d@2x.png"},
        "night": {"description": "Light Snow Showers", "image": "http://openweathermap.org/img/wn/13n@2x.png"},
    },
    "86": {
        "day": {"description": "Snow Showers", "image": "http://openweathermap.org/img/wn/13d@2x.png"},
        "night": {"description": "Snow Showers", "image": "http://openweathermap.org/img/wn/13n@2x.png"},
    },
    "95": {
        "day": {"description": "Thunderstorm", "image": "http://openweathermap.org/img/wn/11d@2x.png"},
        "night": {"description": "Thunderstorm", "image": "http://openweathermap.org/img/wn/11n@2x.png"},
    },
    "96": {
        "day": {"description": "Light Thunderstorms With Hail", "image": "http://openweathermap.org/img/wn/11d@2x.png"},
        "night": {
            "description": "Light Thunderstorms With Hail",
            "image": "http://openweathermap.org/img/wn/11n@2x.png",
        },
    },
    "99": {
        "day": {"description": "Thunderstorm With Hail", "image": "http://openweathermap.org/img/wn/11d@2x.png"},
        "night": {"description": "Thunderstorm With Hail", "image": "http://openweathermap.org/img/wn/11n@2x.png"},
    },
}


def _resolved_tz(name: str) -> tuple[ZoneInfo, str]:
    try:
        z = ZoneInfo(name)
        return z, name
    except Exception:
        return ZoneInfo("UTC"), "UTC"


def _sun_day_and_times(lat: float, lon: float, tz_name: str, now: datetime) -> tuple[bool, str | None, str | None]:
    """
    Whether it is daytime (between sunrise and sunset), plus sunrise/sunset labels.

    Uses astral for the configured coordinates and timezone. Falls back to a coarse
    local-hour heuristic if computation fails (e.g. polar day/night edge cases).
    """
    tz, iana = _resolved_tz(tz_name)
    local_now = now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz)
    try:
        loc = LocationInfo("weather", "", iana, lat, lon)
        s = sun(loc.observer, date=local_now.date(), tzinfo=tz)
        rise, st = s["sunrise"], s["sunset"]
        is_day = rise <= local_now < st
        return is_day, rise.strftime("%H:%M"), st.strftime("%H:%M")
    except Exception:
        is_day = _FALLBACK_DAY_START_HOUR <= local_now.hour < _FALLBACK_DAY_END_HOUR
        return is_day, None, None


def _condition_and_icon_url(code: int, is_day: bool) -> tuple[str, str]:
    """Map WMO weather code to WEATHER_CODES description and icon URL."""
    key = str(code)
    entry = WEATHER_CODES.get(key)
    if entry is None:
        desc = WMO_CODES.get(code, "Unknown")
        entry = WEATHER_CODES["0"]
    else:
        desc = None
    part = "day" if is_day else "night"
    day_night = entry[part]
    description = desc if desc is not None else day_night["description"]
    return description, day_night["image"]


def _paste_icon_top_center(image: Image.Image, zone: Zone, icon_bytes: bytes) -> int:
    """Paste icon centered horizontally at the top; return y for text stacked below."""
    try:
        icon = Image.open(BytesIO(icon_bytes)).convert("RGBA")
    except Exception:
        return max(8, zone.height_percent_int(3))
    pad_top = max(6, zone.height_percent_int(2))
    side_pad = max(8, zone.width_percent_int(3))
    max_w = max(1, zone.width - 2 * side_pad)
    target_h = max(1, zone.height_ratio_int(0.34))
    scale = target_h / max(1, icon.height)
    target_w = int(round(icon.width * scale))
    if target_w > max_w:
        target_w = max_w
        target_h = int(round(icon.height * (target_w / max(1, icon.width))))
    icon = icon.resize((target_w, target_h))
    left = max(0, (zone.width - target_w) // 2)
    layer = icon.convert(image.mode)
    image.paste(layer, (left, pad_top), mask=icon.split()[-1])
    gap = max(6, zone.height_percent_int(2))
    return pad_top + target_h + gap


def _draw_centered_line(
    draw: ImageDraw.ImageDraw,
    zone: Zone,
    text: str,
    *,
    y: int,
    font,
    fill: int,
) -> tuple[int, int]:
    """Draw one line centered horizontally. Returns (line height, next y below line)."""
    tb = draw.textbbox((0, 0), text, font=font)
    tw = tb[2] - tb[0]
    th = tb[3] - tb[1]
    x = int(round((zone.width - tw) / 2)) - tb[0]
    draw.text((x, y), text, font=font, fill=fill)
    return th, y + th


class WeatherPlugin(BasePlugin):
    """Weather plugin – fetches current conditions from Open-Meteo (no key needed)."""

    name = "weather"
    interval = 600  # 10 minutes

    def fetch(self) -> PluginData:
        """Fetch the current weather conditions."""
        lat = float(self.config.get("latitude", 51.5074))
        lon = float(self.config.get("longitude", -0.1278))
        tz_name = str(self.config.get("timezone", "UTC"))
        units = self.config.get("units", "metric")
        temp_unit = "celsius" if units == "metric" else "fahrenheit"

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current_weather=true"
            f"&temperature_unit={temp_unit}"
            f"&windspeed_unit=kmh"
        )
        with urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read())

        cw = body["current_weather"]
        code = int(cw.get("weathercode", 0))
        tz, _ = _resolved_tz(tz_name)
        # Local "now" matches the configured timezone (same idea as the clock plugin).
        is_day, sunrise_hm, sunset_hm = _sun_day_and_times(lat, lon, tz_name, datetime.now(tz))
        condition, icon_url = _condition_and_icon_url(code, is_day)

        icon_bytes: bytes | None = None
        if bool(self.config.get("show_icon", True)) and icon_url:
            try:
                req = Request(icon_url, headers=_DEFAULT_HEADERS)
                with urlopen(req, timeout=10) as img_resp:
                    icon_bytes = img_resp.read()
            except Exception:
                icon_bytes = None

        unit_sym = "°C" if units == "metric" else "°F"
        payload: dict = {
            "temp": f"{cw['temperature']:.0f}{unit_sym}",
            "wind": f"{cw['windspeed']:.0f} km/h",
            "condition": condition,
            "is_day": is_day,
            "icon_bytes": icon_bytes,
        }
        if sunrise_hm and sunset_hm:
            payload["sun_line"] = f"Sunrise {sunrise_hm} · Sunset {sunset_hm}"
        return PluginData(payload=payload)

    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        """Render the current weather conditions."""
        draw = ImageDraw.Draw(image)
        fill = (0, 0, 0)

        temp_font = load_font(self.config, self.config.get("temp_font"), int(self.config.get("temp_font_size", 52)))
        wind_font = load_font(self.config, self.config.get("wind_font"), int(self.config.get("wind_font_size", 20)))
        condition_font = load_font(
            self.config, self.config.get("condition_font"), int(self.config.get("condition_font_size", 20))
        )
        sun_font = load_font(self.config, self.config.get("sun_font"), int(self.config.get("sun_font_size", 14)))

        if data.error:
            err_y = max(8, zone.height_percent_int(8))
            _draw_centered_line(draw, zone, "Weather unavailable", y=err_y, font=condition_font, fill=fill)
            return

        p = data.payload or {}
        y = max(8, zone.height_percent_int(3))
        icon_bytes = p.get("icon_bytes")
        if icon_bytes and bool(self.config.get("show_icon", True)):
            y = _paste_icon_top_center(image, zone, icon_bytes)

        gap_lg = max(4, zone.height_percent_int(2))
        gap_sm = max(2, zone.height_percent_int(1))

        _, y = _draw_centered_line(draw, zone, p.get("temp", "--"), y=y, font=temp_font, fill=fill)
        y += gap_lg
        _, y = _draw_centered_line(draw, zone, p.get("condition", ""), y=y, font=condition_font, fill=fill)
        y += gap_sm
        _, y = _draw_centered_line(draw, zone, f"Wind: {p.get('wind', '--')}", y=y, font=wind_font, fill=fill)
        sun_line = p.get("sun_line")
        if sun_line:
            y += gap_sm
            _draw_centered_line(draw, zone, sun_line, y=y, font=sun_font, fill=fill)
