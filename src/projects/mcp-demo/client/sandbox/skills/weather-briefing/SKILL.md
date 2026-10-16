---
name: weather-briefing
description: Produce a weather briefing for one or more cities — current conditions, multi-day forecast, air quality, travel or packing advice, or a city comparison. Use when the user asks about weather, temperature, humidity, wind, rain, air quality/AQI, or what to pack for a trip.
---

# Weather Briefing

Turn live weather data from the `weather` MCP server into a short, practical briefing.

## Choose the tools
| The user wants… | Call |
|---|---|
| Conditions right now | `weather_get_current_weather` |
| The next few days / a trip | `weather_get_forecast` (days = trip length, max 7) |
| Air quality, pollution, AQI, "is it safe to run outside" | `weather_get_air_quality` |
| Two or more cities side by side | `weather_compare_weather` |

For a trip, call the forecast *and* air quality. Use `units="imperial"` only if the user uses
°F/mph or asks for it.

## Output format
```
## Weather — <City, Country>  (<local observation time>)
<one-line headline, e.g. "Warm and humid with afternoon showers likely">

| Metric | Value |
|---|---|
| Temperature (feels like) | … |
| Humidity | … |
| Wind | <speed> <unit> from <direction> |
| Precipitation | … |
| Air quality | <AQI> — <category> |      (only if fetched)

### Next days            (only if a forecast was fetched)
| Date | Conditions | Min / Max | Rain chance |

### Advice
2–4 bullets: clothing / umbrella / outdoor-activity / health notes derived from the data.
```

## Rules
- Report only values the tools returned, with their units. Never estimate missing values.
- Forecasts start today and reach at most 7 days ahead. If the user's dates ("next week", a
  specific date) fall partly or fully outside that window, say so and show only the days covered.
- If a city isn't found, say so and suggest adding the country (e.g. "Hyderabad, India").
- Flag risks explicitly: rain chance ≥ 60%, wind ≥ 40 km/h, AQI > 100, temperature ≥ 38 °C or ≤ 0 °C.
