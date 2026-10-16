"""Server-side settings. Everything comes from server/.env; paths resolve from this file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

SERVER_DIR = Path(__file__).resolve().parents[1]
load_dotenv(SERVER_DIR / ".env")

DATA_DIR = SERVER_DIR / "data"
DOCS_DIR = DATA_DIR / "documents"
DB_PATH = DATA_DIR / "sales.db"
CHROMA_DIR = SERVER_DIR / ".chroma"
KEYS_DIR = SERVER_DIR / ".keys"

HOST = os.getenv("MCP_HOST", "127.0.0.1")
AUTH_PORT = int(os.getenv("AUTH_PORT", "9000"))
ISSUER = os.getenv("AUTH_ISSUER", f"http://{HOST}:{AUTH_PORT}")
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", "3000"))


@dataclass(frozen=True)
class ResourceServer:
    name: str
    port: int
    scopes: tuple[str, ...]  # every scope this server understands
    required_scope: str      # needed just to connect

    @property
    def url(self) -> str:
        """Resource identifier = the MCP endpoint URL (also the JWT `aud`)."""
        return f"http://{HOST}:{self.port}/mcp"


RESOURCE_SERVERS = {
    "weather": ResourceServer("weather", int(os.getenv("WEATHER_PORT", "8001")),
                              ("weather:read",), "weather:read"),
    "docs": ResourceServer("docs", int(os.getenv("DOCS_PORT", "8002")),
                           ("docs:read", "docs:write"), "docs:read"),
    "sql": ResourceServer("sql", int(os.getenv("SQL_PORT", "8003")),
                          ("sql:read",), "sql:read"),
}

# OAuth clients allowed to use the client_credentials grant. Secrets come from .env;
# a client whose secret is not set is disabled.
CLIENTS = {
    "demo-agent": {
        "secret": os.getenv("DEMO_AGENT_SECRET"),
        "scopes": ["weather:read", "docs:read", "sql:read"],
    },
    "readonly-weather": {  # used to demo 403 insufficient_scope on docs/sql
        "secret": os.getenv("READONLY_WEATHER_SECRET"),
        "scopes": ["weather:read"],
    },
    "docs-admin": {  # the only client allowed to (re)ingest documents
        "secret": os.getenv("DOCS_ADMIN_SECRET"),
        "scopes": ["docs:read", "docs:write"],
    },
}
