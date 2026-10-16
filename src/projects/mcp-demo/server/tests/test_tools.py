"""Tool behaviour via in-process MCP clients (auth off; auth is covered in test_auth.py)."""

import pytest
from mcp import Client

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------- sql
@pytest.fixture(scope="module", autouse=True)
def seeded_db(tmp_path_factory):
    import sql_server.seed_db as seed_mod
    import sql_server.server as sql_mod

    path = tmp_path_factory.mktemp("db") / "sales.db"
    seed_mod.seed(path)
    sql_mod.DB_PATH = path
    yield


@pytest.mark.parametrize("sql", [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "INSERT INTO regions(name, country) VALUES ('x', 'y')",
    "UPDATE products SET unit_price = 0",
    "CREATE TABLE t (x)",
    "ATTACH DATABASE ':memory:' AS x",
    "PRAGMA writable_schema = ON",
    "SELECT 1; DROP TABLE orders",
])
async def test_sql_writes_rejected(sql):
    from sql_server.server import build_server

    async with Client(build_server(auth=False)) as c:
        r = await c.call_tool("run_sql_query", {"sql": sql})
    assert r.is_error and "Rejected" in r.content[0].text


async def test_sql_select_and_cap():
    from sql_server.server import build_server

    async with Client(build_server(auth=False)) as c:
        r = await c.call_tool("run_sql_query", {"sql": "SELECT * FROM orders", "max_rows": 10})
        assert not r.is_error
        assert r.structured_content["row_count"] == 10 and r.structured_content["truncated"] is True
        r = await c.call_tool("describe_table", {"table": "orders; DROP TABLE x"})
        assert r.is_error


# ---------------------------------------------------------------- docs
async def test_docs_retrieval_with_citations(tmp_path, monkeypatch):
    from docs_server import store
    from docs_server.server import build_server

    monkeypatch.setattr(store, "CHROMA_DIR", tmp_path)
    store.ingest()
    async with Client(build_server(auth=False)) as c:
        r = (await c.call_tool("get_context", {"query": "parental leave weeks"})).structured_content
        assert r["found"] and r["citations"][0]["source"] == "employee-handbook.md"
        assert r["context"].startswith("[1]")
        r = (await c.call_tool("get_context", {"query": "chocolate cake recipe"})).structured_content
        assert r["found"] is False


# ---------------------------------------------------------------- weather (HTTP mocked)
async def test_weather_structured_and_errors(monkeypatch):
    import weather_server.server as w
    from mcp.server.mcpserver.exceptions import ToolError

    async def fake_get(url, params):
        if url == w.GEO_URL:
            if params["name"] == "Nowhere":
                return {}
            return {"results": [{"name": "Pune", "country": "India", "latitude": 18.5, "longitude": 73.8,
                                 "timezone": "Asia/Kolkata"}]}
        if url == w.FORECAST_URL:
            return {"current": {"time": "2026-01-01T10:00", "temperature_2m": 25.0, "apparent_temperature": 26.0,
                                "relative_humidity_2m": 60, "wind_speed_10m": 12.0, "wind_direction_10m": 270,
                                "precipitation": 0.0, "surface_pressure": 950.0, "cloud_cover": 20,
                                "weather_code": 2}}
        raise ToolError("unexpected url")

    monkeypatch.setattr(w, "_get", fake_get)
    async with Client(w.build_server(auth=False)) as c:
        r = await c.call_tool("get_current_weather", {"city": "Pune"})
        assert not r.is_error
        sc = r.structured_content
        assert sc["temperature"] == 25.0 and sc["wind_direction"] == "W" and sc["condition"] == "partly cloudy"
        r = await c.call_tool("get_current_weather", {"city": "Nowhere"})
        assert r.is_error and "Could not find" in r.content[0].text
        r = await c.call_tool("get_forecast", {"city": "Pune", "days": 30})
        assert r.is_error  # schema validation: days <= 7
