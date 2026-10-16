"""Weather MCP server (port 8001, scope weather:read). Data: Open-Meteo (free, no API key).

Tools return Pydantic models, so clients get both `structuredContent` (typed JSON, with an
output schema visible in Inspector) and a text rendering for the model.
"""

from __future__ import annotations

from typing import Annotated, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from common.auth import auth_config
from common.config import RESOURCE_SERVERS
from common.logs import request_logger, setup_logging

SERVER = RESOURCE_SERVERS["weather"]
log = setup_logging("weather")

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "heavy showers", 82: "violent showers", 95: "thunderstorm", 96: "thunderstorm with hail",
    99: "severe thunderstorm",
}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)

City = Annotated[str, Field(min_length=2, max_length=80, description="City name, e.g. 'Bengaluru'")]
Units = Literal["metric", "imperial"]


# --------------------------------------------------------------------------- #
# Output models (become the tools' outputSchema)
# --------------------------------------------------------------------------- #
class Location(BaseModel):
    name: str
    country: str
    latitude: float
    longitude: float
    timezone: str


class CurrentWeather(BaseModel):
    location: Location
    observed_at: str
    condition: str
    temperature: float
    feels_like: float
    humidity_pct: float
    wind_speed: float
    wind_direction: str
    precipitation: float
    pressure_hpa: float
    cloud_cover_pct: float
    units: dict[str, str]


class DailyForecast(BaseModel):
    date: str
    condition: str
    temp_min: float
    temp_max: float
    precipitation_probability_pct: float | None
    precipitation_sum: float
    wind_speed_max: float


class Forecast(BaseModel):
    location: Location
    days: list[DailyForecast]
    units: dict[str, str]


class AirQuality(BaseModel):
    location: Location
    us_aqi: float | None
    category: str
    pm2_5: float | None
    pm10: float | None


class WeatherComparison(BaseModel):
    cities: list[CurrentWeather]
    not_found: list[str]


# --------------------------------------------------------------------------- #
# Open-Meteo helpers (errors become ToolError -> isError=True, readable by the model)
# --------------------------------------------------------------------------- #
async def _get(url: str, params: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except httpx.TimeoutException:
        raise ToolError("Weather service timed out; try again shortly.")
    except httpx.HTTPError as e:
        raise ToolError(f"Weather service unavailable: {e}")


async def geocode(city: str) -> Location:
    data = await _get(GEO_URL, {"name": city, "count": 1})
    if not data.get("results"):
        raise ToolError(f"Could not find a city called '{city}'. Check the spelling or add the country.")
    p = data["results"][0]
    return Location(name=p["name"], country=p.get("country", ""), latitude=p["latitude"],
                    longitude=p["longitude"], timezone=p.get("timezone", "auto"))


def _unit_params(units: Units) -> dict:
    return ({"temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch"}
            if units == "imperial" else {})


def _unit_labels(units: Units) -> dict[str, str]:
    return ({"temperature": "°F", "wind_speed": "mph", "precipitation": "inch"} if units == "imperial"
            else {"temperature": "°C", "wind_speed": "km/h", "precipitation": "mm"})


def _aqi_category(aqi: float | None) -> str:
    if aqi is None:
        return "unknown"
    for limit, label in [(50, "good"), (100, "moderate"), (150, "unhealthy for sensitive groups"),
                         (200, "unhealthy"), (300, "very unhealthy")]:
        if aqi <= limit:
            return label
    return "hazardous"


async def _current(city: str, units: Units) -> CurrentWeather:
    loc = await geocode(city)
    c = (await _get(FORECAST_URL, {
        "latitude": loc.latitude, "longitude": loc.longitude, "timezone": "auto",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,"
                   "wind_direction_10m,precipitation,surface_pressure,cloud_cover,weather_code",
        **_unit_params(units),
    }))["current"]
    return CurrentWeather(
        location=loc, observed_at=c["time"], condition=WMO.get(c["weather_code"], f"code {c['weather_code']}"),
        temperature=c["temperature_2m"], feels_like=c["apparent_temperature"],
        humidity_pct=c["relative_humidity_2m"], wind_speed=c["wind_speed_10m"],
        wind_direction=COMPASS[round(c["wind_direction_10m"] / 45) % 8], precipitation=c["precipitation"],
        pressure_hpa=c["surface_pressure"], cloud_cover_pct=c["cloud_cover"], units=_unit_labels(units),
    )


# --------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------- #
def build_server(auth: bool = True) -> MCPServer:
    mcp = MCPServer(
        "weather",
        instructions="Live weather: current conditions, daily forecast, air quality and city comparison.",
        middleware=[request_logger(log)],
        **(auth_config(SERVER) if auth else {}),
    )

    @mcp.tool(annotations=READ_ONLY)
    async def get_current_weather(city: City, units: Units = "metric") -> CurrentWeather:
        """Current conditions for a city: temperature, feels-like, humidity, wind speed and
        direction, precipitation, pressure, cloud cover and a condition description."""
        return await _current(city, units)

    @mcp.tool(annotations=READ_ONLY)
    async def get_forecast(city: City, days: Annotated[int, Field(ge=1, le=7)] = 3,
                           units: Units = "metric") -> Forecast:
        """Daily forecast (1-7 days): min/max temperature, rain probability and amount, max wind."""
        loc = await geocode(city)
        d = (await _get(FORECAST_URL, {
            "latitude": loc.latitude, "longitude": loc.longitude, "timezone": "auto", "forecast_days": days,
            "daily": "weather_code,temperature_2m_min,temperature_2m_max,precipitation_probability_max,"
                     "precipitation_sum,wind_speed_10m_max",
            **_unit_params(units),
        }))["daily"]
        return Forecast(location=loc, units=_unit_labels(units), days=[
            DailyForecast(date=d["time"][i], condition=WMO.get(d["weather_code"][i], "unknown"),
                          temp_min=d["temperature_2m_min"][i], temp_max=d["temperature_2m_max"][i],
                          precipitation_probability_pct=d["precipitation_probability_max"][i],
                          precipitation_sum=d["precipitation_sum"][i], wind_speed_max=d["wind_speed_10m_max"][i])
            for i in range(len(d["time"]))
        ])

    @mcp.tool(annotations=READ_ONLY)
    async def get_air_quality(city: City) -> AirQuality:
        """Current air quality for a city: US AQI (with category), PM2.5 and PM10 (µg/m³)."""
        loc = await geocode(city)
        c = (await _get(AIR_URL, {"latitude": loc.latitude, "longitude": loc.longitude,
                                  "current": "us_aqi,pm2_5,pm10"}))["current"]
        return AirQuality(location=loc, us_aqi=c.get("us_aqi"), category=_aqi_category(c.get("us_aqi")),
                          pm2_5=c.get("pm2_5"), pm10=c.get("pm10"))

    @mcp.tool(annotations=READ_ONLY)
    async def compare_weather(cities: Annotated[list[City], Field(min_length=2, max_length=5)],
                              units: Units = "metric") -> WeatherComparison:
        """Current conditions for 2-5 cities side by side. Unknown cities are listed in `not_found`."""
        found, missing = [], []
        for city in cities:
            try:
                found.append(await _current(city, units))
            except ToolError:
                missing.append(city)
        if not found:
            raise ToolError(f"None of these cities were found: {', '.join(cities)}")
        return WeatherComparison(cities=found, not_found=missing)

    @mcp.prompt()
    def travel_weather_brief(city: str, dates: str) -> str:
        """Prompt template: a packing/travel weather brief for a trip."""
        return (f"I'm travelling to {city} on {dates}. Use get_forecast (and get_air_quality) for "
                f"{city}, then give a short brief: expected conditions per day, what to pack, and any "
                "weather or air-quality risks.")

    return mcp


def main() -> None:
    from common.serve import serve

    serve(build_server(), SERVER)
