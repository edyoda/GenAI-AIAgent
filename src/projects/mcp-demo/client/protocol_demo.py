"""Raw MCP protocol walkthrough: no LLM, no LangChain, zero tokens.

Shows exactly what a client does on the wire, for each server:
    get token -> initialize -> tools/list, resources/list, prompts/list -> tools/call
then the failure cases: no token (401), a client without the scope (403), a tool-level scope
check (docs:write), and the SQL write guard.

    uv run --project src/projects/mcp-demo/client python src/projects/mcp-demo/client/protocol_demo.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

from auth import TokenManager  # noqa: E402
from mcp_connections import AUTH_URL, SERVER_URLS, classify  # noqa: E402

DEMO_CALLS = {
    "weather": ("get_current_weather", {"city": "Bengaluru"}),
    "docs": ("get_context", {"query": "How many days of annual leave do employees get?", "k": 2}),
    "sql": ("run_sql_query", {"sql": "SELECT r.name AS region, COUNT(*) AS orders FROM orders o "
                                     "JOIN customers c USING(customer_id) JOIN regions r USING(region_id) "
                                     "GROUP BY r.name ORDER BY orders DESC"}),
}


def h(title: str) -> None:
    print(f"\n{'─' * 78}\n{title}\n{'─' * 78}")


def short(obj, n: int = 400) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str) if not isinstance(obj, str) else obj
    return s if len(s) <= n else s[:n] + " …"


async def session_for(url: str, auth: httpx.Auth | None):
    http = httpx.AsyncClient(auth=auth, timeout=httpx.Timeout(30, read=120), follow_redirects=True)
    return http, streamable_http_client(url, http_client=http)


async def walkthrough(name: str, tm: TokenManager) -> None:
    url = SERVER_URLS[name]
    h(f"[{name}] {url}")
    await tm.get_token()
    print(f"token: scope='{tm.scope}'  aud={tm.resource}")
    http, transport = await session_for(url, tm)
    async with http, transport as (read, write, _), ClientSession(read, write) as session:
        init = await session.initialize()
        print(f"initialize → server={init.serverInfo.name}  protocol={init.protocolVersion}")
        print(f"  instructions: {init.instructions}")
        tools = (await session.list_tools()).tools
        print(f"tools/list → {len(tools)} tools")
        for t in tools:
            hints = t.annotations
            ro = "read-only" if hints and hints.readOnlyHint else "writes"
            print(f"  • {t.name:22} [{ro}] {(t.description or '').splitlines()[0][:70]}")
        if init.capabilities.resources:
            res = (await session.list_resources()).resources
            print(f"resources/list → {[str(r.uri) for r in res]}")
        if init.capabilities.prompts:
            prompts = (await session.list_prompts()).prompts
            print(f"prompts/list → {[p.name for p in prompts]}")
        tool, args = DEMO_CALLS[name]
        result = await session.call_tool(tool, args)
        print(f"tools/call {tool}({short(args, 120)})\n  isError={result.isError}")
        print(f"  structuredContent: {short(result.structuredContent)}")


async def expect_failure(title: str, url: str, auth: httpx.Auth | None) -> None:
    http, transport = await session_for(url, auth)
    try:
        async with http, transport as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
        print(f"✗ {title}: unexpectedly succeeded")
    except BaseException as e:  # noqa: BLE001 (transport errors come wrapped in ExceptionGroups)
        print(f"✓ {title}: {classify(e)[1]}")


async def tool_error(title: str, tm: TokenManager, url: str, tool: str, args: dict) -> None:
    http, transport = await session_for(url, tm)
    async with http, transport as (read, write, _), ClientSession(read, write) as session:
        await session.initialize()
        r = await session.call_tool(tool, args)
        print(f"{'✓' if r.isError else '✗'} {title}: isError={r.isError} → {r.content[0].text}")


async def main() -> None:
    cid, secret = os.getenv("MCP_CLIENT_ID", "demo-agent"), os.getenv("MCP_CLIENT_SECRET", "")
    tms = {n: TokenManager(f"{AUTH_URL}/token", cid, secret, resource=u) for n, u in SERVER_URLS.items()}

    for name in SERVER_URLS:
        try:
            await walkthrough(name, tms[name])
        except BaseException as e:  # noqa: BLE001
            print(f"✗ {name}: {classify(e)[1]}")

    h("Failure handling")
    await expect_failure("no token → sql", SERVER_URLS["sql"], None)
    ro_id, ro_secret = os.getenv("READONLY_CLIENT_ID", "readonly-weather"), os.getenv("READONLY_CLIENT_SECRET", "")
    if ro_secret:
        ro = TokenManager(f"{AUTH_URL}/token", ro_id, ro_secret, resource=SERVER_URLS["sql"])
        await expect_failure(f"'{ro_id}' token (no sql:read) → sql", SERVER_URLS["sql"], ro)
    weather_token_on_sql = TokenManager(f"{AUTH_URL}/token", cid, secret, resource=SERVER_URLS["weather"])
    await expect_failure("weather-audience token → sql", SERVER_URLS["sql"], _Fixed(weather_token_on_sql))
    await tool_error("ingest_documents without docs:write", tms["docs"], SERVER_URLS["docs"], "ingest_documents", {})
    await tool_error("write attempt via run_sql_query", tms["sql"], SERVER_URLS["sql"], "run_sql_query",
                     {"sql": "DROP TABLE orders"})


class _Fixed(httpx.Auth):
    """Sends another server's token as-is (no refresh), to show audience binding → 401."""

    def __init__(self, tm: TokenManager):
        self.tm = tm

    async def async_auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {await self.tm.get_token()}"
        yield request


if __name__ == "__main__":
    asyncio.run(main())
