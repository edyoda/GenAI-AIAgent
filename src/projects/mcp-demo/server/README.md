# MCP demo — server side

A standalone project: an OAuth auth server and three MCP servers (weather, docs, sql). Each
runs as its own process. See [../README.md](../README.md) for the full walkthrough.

```
auth_server/app.py        :9000  POST /token, /.well-known/jwks.json, /.well-known/oauth-authorization-server
weather_server/server.py  :8001  /mcp   (Open-Meteo, no key)
docs_server/server.py     :8002  /mcp   (+ store.py: Chroma, local embeddings)
sql_server/server.py      :8003  /mcp   (+ seed_db.py: deterministic SQLite sales DB)
common/                   config (.env), JWT verifier, request logging, serve()
main.py                   setup | all | auth | weather | docs | sql | token | seed-db | ingest
tests/                    pytest, no network or LLM needed
```

```bash
cp .env.example .env
uv run python main.py setup    # once
uv run python main.py all
uv run python main.py token --client demo-agent --server sql   # bearer token for MCP Inspector
uv run pytest -q
```
