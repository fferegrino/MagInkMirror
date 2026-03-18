"""Weather plugin – fetches current conditions from Open-Meteo (no key needed)."""

from __future__ import annotations

import json
import urllib.request

from PIL import Image, ImageDraw

from maginkmirror.core.fonts import load_font
from maginkmirror.plugins import BasePlugin, PluginData, Zone

PLUGIN_CLASS = "WeatherPlugin"

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


class WeatherPlugin(BasePlugin):
    """Weather plugin – fetches current conditions from Open-Meteo (no key needed)."""

    name = "weather"
    interval = 600  # 10 minutes

    def fetch(self) -> PluginData:
        """Fetch the current weather conditions."""
        lat = self.config.get("latitude", 51.5074)
        lon = self.config.get("longitude", -0.1278)
        units = self.config.get("units", "metric")
        temp_unit = "celsius" if units == "metric" else "fahrenheit"

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current_weather=true"
            f"&temperature_unit={temp_unit}"
            f"&windspeed_unit=kmh"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read())

        cw = body["current_weather"]
        unit_sym = "°C" if units == "metric" else "°F"
        return PluginData(
            payload={
                "temp": f"{cw['temperature']:.0f}{unit_sym}",
                "wind": f"{cw['windspeed']:.0f} km/h",
                "condition": WMO_CODES.get(cw.get("weathercode", 0), "Unknown"),
            }
        )

    def render(self, data: PluginData, image: Image.Image, zone: Zone) -> None:
        """Render the current weather conditions."""
        draw = ImageDraw.Draw(image)
        fill = 0

        temp_font = load_font(self.config, self.config.get("temp_font"), int(self.config.get("temp_font_size", 52)))
        wind_font = load_font(self.config, self.config.get("wind_font"), int(self.config.get("wind_font_size", 20)))
        condition_font = load_font(
            self.config, self.config.get("condition_font"), int(self.config.get("condition_font_size", 20))
        )

        if data.error:
            draw.text((10, 10), "Weather unavailable", font=condition_font, fill=fill)
            return

        p = data.payload
        draw.text((20, 20), p.get("temp", "--"), font=temp_font, fill=fill)
        draw.text((20, 90), p.get("condition", ""), font=condition_font, fill=fill)
        draw.text((20, 116), f"Wind: {p.get('wind', '--')}", font=wind_font, fill=fill)
