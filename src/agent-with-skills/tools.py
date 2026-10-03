"""Regular (non-skill) tools the agent can call directly.

- get_weather : live weather via Open-Meteo (free, no API key needed)
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from langchain.tools import tool

# WMO weather codes -> short description
_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    80: "rain showers", 81: "heavy showers", 82: "violent showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm",
}


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310 (fixed https hosts)
        return json.loads(r.read().decode())


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city. Input is a city name, e.g. 'Bengaluru'."""
    try:
        q = urllib.parse.quote(city)
        geo = _get_json(f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1")
        if not geo.get("results"):
            return f"Could not find a city called '{city}'."
        place = geo["results"][0]
        wx = _get_json(
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={place['latitude']}&longitude={place['longitude']}"
            "&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
        )["current"]
    except Exception as e:  # network errors go back to the model instead of crashing the run
        return f"Weather service unavailable for '{city}': {e}"
    desc = _WMO.get(wx["weather_code"], f"code {wx['weather_code']}")
    return (
        f"{place['name']}, {place.get('country', '')}: {desc}, "
        f"{wx['temperature_2m']}°C, humidity {wx['relative_humidity_2m']}%, "
        f"wind {wx['wind_speed_10m']} km/h"
    )


TOOLS = [get_weather]
