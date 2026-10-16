"""Connections to the three MCP servers: config, health check, tools, and error handling.

- Each server gets its own TokenManager (tokens are bound to one server).
- `connect()` checks every server once at startup. A server that is down or rejects our
  credentials is skipped with a clear reason, and the agent runs with the rest.
- `resilient_tool_calls` wraps every tool call: transient network errors are retried with
  backoff; anything else (401/403, server gone) becomes a readable tool error for the model
  instead of crashing the run. Errors the server reports itself (isError=True) already reach
  the model as error ToolMessages (handle_tool_errors=True).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

import httpx
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from mcp import McpError
from mcp.types import CallToolResult, TextContent

from auth import AuthError, TokenManager

log = logging.getLogger("mcp-client")

AUTH_URL = os.getenv("AUTH_URL", "http://127.0.0.1:9000")
SERVER_URLS = {
    "weather": os.getenv("WEATHER_MCP_URL", "http://127.0.0.1:8001/mcp"),
    "docs": os.getenv("DOCS_MCP_URL", "http://127.0.0.1:8002/mcp"),
    "sql": os.getenv("SQL_MCP_URL", "http://127.0.0.1:8003/mcp"),
}
MAX_ATTEMPTS = 3


@dataclass
class ServerStatus:
    name: str
    url: str
    ok: bool = False
    tools: list[str] = field(default_factory=list)
    scope: str = ""
    error: str = ""


# --------------------------------------------------------------------------- #
# Error classification (transport errors often arrive wrapped in ExceptionGroups)
# --------------------------------------------------------------------------- #
def _leaves(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for e in exc.exceptions for leaf in _leaves(e)]
    return [exc]


def classify(exc: BaseException) -> tuple[str, str]:
    """-> (kind, message). kind: 'transient' (worth retrying) or 'fatal'."""
    for e in _leaves(exc):
        if isinstance(e, AuthError):
            return "fatal", f"authentication failed: {e}"
        if isinstance(e, httpx.HTTPStatusError):
            code = e.response.status_code
            www = e.response.headers.get("www-authenticate", "")
            if code == 401:
                return "fatal", "unauthorized (401): token missing, invalid, expired or issued for another server"
            if code == 403:
                need = www.split("Required scope:")[-1].split('"')[0].strip() if "Required scope" in www else "?"
                return "fatal", f"forbidden (403): this client lacks the '{need}' scope"
            if code in (502, 503, 504):
                return "transient", f"server busy ({code})"
            return "fatal", f"HTTP {code} from server"
        if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
            return "transient", "server unreachable"
        if isinstance(e, (httpx.ReadTimeout, httpx.RemoteProtocolError)):
            return "transient", "connection dropped / timed out"
        if isinstance(e, McpError):
            return "fatal", f"MCP error: {e.error.message}"
    first = _leaves(exc)[0]
    return "fatal", f"{type(first).__name__}: {first}"


async def resilient_tool_calls(request: MCPToolCallRequest, handler):
    """Tool-call interceptor: retry transient failures, turn the rest into tool errors."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await handler(request)
        except Exception as e:  # noqa: BLE001 (we classify below)
            kind, msg = classify(e)
            if kind == "transient" and attempt < MAX_ATTEMPTS:
                delay = 0.5 * 2 ** (attempt - 1)
                log.warning("%s.%s: %s, retrying in %.1fs (%d/%d)", request.server_name, request.name,
                            msg, delay, attempt, MAX_ATTEMPTS - 1)
                await asyncio.sleep(delay)
                continue
            log.warning("%s.%s failed: %s", request.server_name, request.name, msg)
            return CallToolResult(isError=True, content=[TextContent(
                type="text", text=f"The '{request.server_name}' MCP server could not run {request.name}: {msg}")])


# --------------------------------------------------------------------------- #
# Connect
# --------------------------------------------------------------------------- #
def token_managers(client_id: str | None = None, client_secret: str | None = None) -> dict[str, TokenManager]:
    client_id = client_id or os.getenv("MCP_CLIENT_ID", "demo-agent")
    client_secret = client_secret or os.getenv("MCP_CLIENT_SECRET", "")
    return {name: TokenManager(f"{AUTH_URL}/token", client_id, client_secret, resource=url)
            for name, url in SERVER_URLS.items()}


async def connect(names: list[str] | None = None) -> tuple[list[BaseTool], dict[str, ServerStatus], MultiServerMCPClient]:
    names = names or list(SERVER_URLS)
    auths = token_managers()
    client = MultiServerMCPClient(
        {name: {"transport": "streamable_http", "url": SERVER_URLS[name], "auth": auths[name],
                "timeout": 30, "sse_read_timeout": 120} for name in names},
        tool_name_prefix=True,  # weather_get_forecast, sql_run_sql_query, ...
        tool_interceptors=[resilient_tool_calls],
        handle_tool_errors=True,
    )
    tools: list[BaseTool] = []
    statuses: dict[str, ServerStatus] = {}
    for name in names:
        status = ServerStatus(name, SERVER_URLS[name])
        try:
            server_tools = await client.get_tools(server_name=name)  # initialize + tools/list
            tools += server_tools
            status.ok, status.tools = True, [t.name for t in server_tools]
        except Exception as e:  # noqa: BLE001
            status.error = classify(e)[1]
        status.scope = auths[name].scope
        statuses[name] = status
    return tools, statuses, client
