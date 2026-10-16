# MCP demo — client side

A standalone project: a LangChain ReAct agent whose tools come from the three MCP servers,
plus skills. See [../README.md](../README.md) for the full walkthrough.

```
auth.py              TokenManager (httpx.Auth): client_credentials, cache, early refresh, 401 → refresh + replay
mcp_connections.py   server URLs, startup health check, error classification, retry interceptor
agent.py             create_agent + MCP tools + SkillsMiddleware + read-only ls/read_file
main.py              chat REPL / --once, live tool log, LangSmith run config
protocol_demo.py     raw MCP session walkthrough + 401/403/tool-error cases (no LLM)
sandbox/skills/      weather-briefing, document-qa, sql-analyst
```

```bash
cp .env.example .env         # MCP_CLIENT_SECRET must match server/.env; add your LLM key
uv run python protocol_demo.py
uv run python main.py
```
