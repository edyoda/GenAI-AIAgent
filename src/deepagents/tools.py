"""Custom tools added on top of the deep agent's built-in ones.

- get_weather : current weather + optional daily forecast via Open-Meteo (free, no API key)
- calculate   : safe arithmetic and common math functions (no eval)
- web_search  : Tavily web search (needs TAVILY_API_KEY; skipped if the key is missing)
"""

from __future__ import annotations

import ast
import json
import math
import operator
import os
import urllib.parse
import urllib.request

from langchain.tools import tool
from langchain_core.tools import BaseTool

# --------------------------------------------------------------------------- #
# 1. Weather  (Open-Meteo: free, no API key needed)
# --------------------------------------------------------------------------- #
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
def get_weather(city: str, forecast_days: int = 0) -> str:
    """Get the current weather for a city, e.g. 'Bengaluru'.

    Set forecast_days (1-7) to also get a daily forecast (min/max temperature, rain chance).
    """
    forecast_days = max(0, min(int(forecast_days), 7))
    try:
        q = urllib.parse.quote(city)
        geo = _get_json(f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1")
        if not geo.get("results"):
            return f"Could not find a city called '{city}'."
        place = geo["results"][0]
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={place['latitude']}&longitude={place['longitude']}&timezone=auto"
            "&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
        )
        if forecast_days:
            url += (f"&forecast_days={forecast_days}&daily=weather_code,temperature_2m_max,"
                    "temperature_2m_min,precipitation_probability_max")
        data = _get_json(url)
    except Exception as e:  # network errors go back to the model instead of crashing the run
        return f"Weather service unavailable for '{city}': {e}"

    wx = data["current"]
    lines = [
        f"{place['name']}, {place.get('country', '')} now: "
        f"{_WMO.get(wx['weather_code'], f'code {wx['weather_code']}')}, "
        f"{wx['temperature_2m']}°C, humidity {wx['relative_humidity_2m']}%, "
        f"wind {wx['wind_speed_10m']} km/h"
    ]
    if forecast_days:
        d = data["daily"]
        for i, day in enumerate(d["time"]):
            lines.append(
                f"  {day}: {_WMO.get(d['weather_code'][i], 'n/a')}, "
                f"{d['temperature_2m_min'][i]}–{d['temperature_2m_max'][i]}°C, "
                f"rain chance {d['precipitation_probability_max'][i]}%"
            )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 2. Calculator  (safe arithmetic via the AST, no eval())
# --------------------------------------------------------------------------- #
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_FUNCS = {
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "exp": math.exp,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "abs": abs, "round": round, "min": min, "max": max,
}
_CONSTS = {"pi": math.pi, "e": math.e}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS and not node.keywords):
        return _FUNCS[node.func.id](*(_eval(a) for a in node.args))
    raise ValueError(
        "Only numbers, + - * / // % ** ( ), pi, e and "
        f"{', '.join(_FUNCS)} are allowed"
    )


@tool
def calculate(expression: str) -> str:
    """Evaluate a math expression exactly, e.g. '(23 * 7) + 12 / 4' or 'sqrt(2) * pi'.

    Supports + - * / // % ** and parentheses, constants pi and e, and the functions
    sqrt, log, log10, exp, sin, cos, tan, abs, round, min, max.
    Use this for any arithmetic instead of computing in your head.
    """
    try:
        result = _eval(ast.parse(expression, mode="eval").body)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Could not evaluate '{expression}': {e}"


# --------------------------------------------------------------------------- #
# 3. Web search  (Tavily)
# --------------------------------------------------------------------------- #
def build_web_search() -> BaseTool | None:
    """Tavily search tool, or None when TAVILY_API_KEY isn't set."""
    if not os.getenv("TAVILY_API_KEY"):
        return None
    from langchain_tavily import TavilySearch

    return TavilySearch(
        name="web_search",
        description=(
            "Search the web for current information, news and facts. "
            "Returns result titles, URLs and content snippets. Cite the URLs you use."
        ),
        max_results=5,
        topic="general",
    )


def build_tools() -> list[BaseTool]:
    tools: list[BaseTool] = [get_weather, calculate]
    if search := build_web_search():
        tools.append(search)
    return tools
