"""The three tools the agent can use.

- get_weather : read-only, safe -> runs WITHOUT human approval
- calculate   : read-only, but we still want a human to sanity-check it -> approve / reject
- send_email  : has side effects (sends something out) -> approve / edit / reject
"""

from __future__ import annotations

import ast
import json
import operator
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from langchain.tools import tool

# --------------------------------------------------------------------------- #
# 1. Weather  (Open-Meteo: free, no API key needed)
# --------------------------------------------------------------------------- #
_WMO = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "dense drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "rain showers",
    81: "heavy showers",
    82: "violent showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "severe thunderstorm",
}


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310 (fixed https hosts)
        return json.loads(r.read().decode())


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city. Input is a city name, e.g. 'Bengaluru'."""
    # Network errors are raised on purpose: ToolRetryMiddleware retries them with backoff,
    # and if all retries fail the model gets a clean error message instead of a crash.
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
    desc = _WMO.get(wx["weather_code"], f"code {wx['weather_code']}")
    return (
        f"{place['name']}, {place.get('country', '')}: {desc}, "
        f"{wx['temperature_2m']}°C, humidity {wx['relative_humidity_2m']}%, "
        f"wind {wx['wind_speed_10m']} km/h"
    )


# --------------------------------------------------------------------------- #
# 2. Calculator  (safe arithmetic, no eval())
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


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("Only numbers and + - * / // % ** ( ) are allowed")


@tool
def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression, e.g. '(23 * 7) + 12 / 4'. Supports + - * / // % ** and parentheses."""
    try:
        result = _eval(ast.parse(expression, mode="eval").body)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Could not evaluate '{expression}': {e}"


# --------------------------------------------------------------------------- #
# 3. Send email  (simulated: writes to outbox.jsonl instead of really sending)
# --------------------------------------------------------------------------- #
OUTBOX = Path(__file__).parent / "outbox.jsonl"


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient. Use only when the user explicitly asks to send/email something."""
    record = {
        "sent_at": datetime.now().isoformat(timespec="seconds"),
        "to": to,
        "subject": subject,
        "body": body,
    }
    with OUTBOX.open("a") as f:
        f.write(json.dumps(record) + "\n")
    return f"Email sent to {to} with subject '{subject}'."


ALL_TOOLS = [get_weather, calculate, send_email]
