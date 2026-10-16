# MCP demo: authenticated MCP servers + a skills-enabled agent client

Two **completely independent** codebases that only talk over HTTP using the Model Context
Protocol:

| | `server/` | `client/` |
|---|---|---|
| What | 1 auth server + 3 MCP servers, each its own process | LangChain ReAct agent + skills |
| SDK | `mcp` **2.2** (`MCPServer`) | `mcp` **1.30** + `langchain-mcp-adapters` |
| Own | `pyproject.toml`, `uv.lock`, `.venv`, `.env` | `pyproject.toml`, `uv.lock`, `.venv`, `.env` |

They don't import each other's code, and they even run different MCP SDK versions. They
interoperate only because both follow the protocol.

```
                      ┌──────────────── server/ ────────────────┐
                      │  auth_server   :9000  POST /token, JWKS │
 client/              │     ▲ JWKS (public key)                 │
 ┌──────────────┐     │     │                                   │
 │ ReAct agent  │ ──1─┼─► /token  (client_credentials, resource)│
 │  + skills    │     │                                         │
 │ TokenManager │ ──2─┼─► weather :8001/mcp  scope weather:read │  Open-Meteo
 │ (httpx.Auth) │ ──2─┼─► docs    :8002/mcp  scope docs:read    │  Chroma (local embeddings)
 └──────────────┘ ──2─┼─► sql     :8003/mcp  scope sql:read     │  SQLite (read-only)
                      └─────────────────────────────────────────┘
 1 = get a JWT per server (aud = that server's URL)   2 = MCP over Streamable HTTP + Bearer token
```

## The three servers

| Server | Tools | Resources / prompts |
|---|---|---|
| **weather** | `get_current_weather` (temp, feels-like, humidity, wind, pressure, clouds, rain), `get_forecast` (1–7 days), `get_air_quality` (AQI, PM2.5, PM10), `compare_weather` | prompt `travel_weather_brief` |
| **docs** | `list_documents`, `search_documents` (scored chunks), `get_context` (merged context + `[n]` citations), `get_chunk` (with neighbours), `ingest_documents` (**needs `docs:write`**) | resource `docs://catalog` |
| **sql** | `list_tables`, `describe_table`, `get_sample_rows`, `run_sql_query`, `explain_query`, `profile_column` | resource `schema://database`, prompt `analyze_business_question` |

- Every tool has Pydantic-typed input (bounds are validated) and output. Clients get
  `structuredContent` plus an `outputSchema`, which you can see in Inspector.
- Expected failures (unknown city, bad SQL, missing index) raise `ToolError`. The client then
  receives `isError: true` with a readable message instead of a crash.
- SQL is read-only in several layers:
  - the database is opened with `mode=ro` and `PRAGMA query_only`
  - an sqlite **authorizer** permits reads only
  - one statement per call
  - a row cap
  - a 5 s timeout

## Authentication (OAuth 2.1 client credentials + JWT + scopes)

1. The client posts `grant_type=client_credentials&resource=<server URL>` to `auth :9000/token`,
   using HTTP Basic auth with `client_id:client_secret`.
2. The auth server returns an **RS256 JWT** containing:
   - `aud` = that one server's URL
   - `scope` = requested ∩ the client's allowed scopes ∩ the server's scopes
   - `exp` = 5 minutes after issue
3. Each MCP server checks the signature against the auth server's **JWKS** (it never sees the
   private key), then checks `exp`, `iss` and `aud`. The MCP SDK then enforces the rules:

| Situation | Response |
|---|---|
| No token / bad signature / expired / token for another server / wrong issuer | **401** + `WWW-Authenticate: Bearer … resource_metadata="…"` |
| Valid token, missing required scope | **403** `insufficient_scope` |
| Connected, but tool needs an extra scope (`ingest_documents`) | tool result `isError: true` |

Each server also serves `/.well-known/oauth-protected-resource/mcp`, which tells clients
which auth server to use (RFC 9728).

Demo clients (secrets in `server/.env`):

| client_id | scopes | used for |
|---|---|---|
| `demo-agent` | `weather:read docs:read sql:read` | the agent |
| `readonly-weather` | `weather:read` | showing a 403 on docs/sql |
| `docs-admin` | `docs:read docs:write` | calling `ingest_documents` |

### How the client handles requests

- **`TokenManager` (`httpx.Auth`)**:
  - fetches a token per server and caches it
  - refreshes it 30 s before expiry
  - on a **401**, refreshes once and **replays** the request
  - never retries a **403**
- **Startup health check**: a server that is down or refuses the client is skipped with a
  reason (`/servers` shows it). The agent runs with the rest, and the system prompt tells the
  model what is unavailable.
- **Tool-call interceptor**: retries transient network errors with backoff (0.5 s, then 1 s).
  Anything else becomes a tool error the model can read and explain, so the run never crashes.
- **Server-side tool errors** (`isError`) reach the model as error `ToolMessage`s, so it can
  self-correct, for example by fixing an SQL column name.

## Skills (client side)

Servers provide **capabilities** and skills provide the **procedure**. The system prompt holds
only each skill's name and description; the agent reads `SKILL.md` when a request matches.

| Skill | Triggers on | Procedure |
|---|---|---|
| `weather-briefing` | weather, forecast, AQI, packing | pick the right tools → metrics table, forecast table, risk flags and advice |
| `document-qa` | policy, entitlement, product questions | `get_context` → relevance check → answer only from passages with `[n]` citations |
| `sql-analyst` | business and data questions | schema first → plan → `explain_query` → run → sanity-check → insight, table and SQL |

## Run it (from the repo root)

```bash
# ── server ─────────────────────────────────────────────
cp src/projects/mcp-demo/server/.env.example src/projects/mcp-demo/server/.env        # set the 3 client secrets
uv sync --project src/projects/mcp-demo/server
uv run --project src/projects/mcp-demo/server python src/projects/mcp-demo/server/main.py setup   # seed DB + index docs (once)
uv run --project src/projects/mcp-demo/server python src/projects/mcp-demo/server/main.py all     # 4 processes; Ctrl-C stops all
#   or one per terminal: main.py auth | weather | docs | sql

# ── client (another terminal) ──────────────────────────
cp src/projects/mcp-demo/client/.env.example src/projects/mcp-demo/client/.env        # same demo-agent secret + LLM key
uv sync --project src/projects/mcp-demo/client
uv run --project src/projects/mcp-demo/client python src/projects/mcp-demo/client/protocol_demo.py   # raw MCP, no LLM
uv run --project src/projects/mcp-demo/client python src/projects/mcp-demo/client/main.py            # the agent
```

In VS Code, use the **MCP servers (auth + weather + docs + sql)** compound launch, then
**MCP client agent** or **MCP protocol demo (no LLM)**.

Try:
- `What's the weather in Pune for the next 3 days, and what should I pack?` (weather-briefing)
- `How many days of annual leave do I get, and how many carry over?` (document-qa)
- `What's the hotel cap in Hyderabad and do I need approval for a 60,000 INR trip?` (document-qa)
- `Which product category had the highest gross margin in 2025?` (sql-analyst)
- `Compare revenue by channel month over month for Q4 2025` (sql-analyst)

Chat commands: `/servers`, `/skills`, `/new`, `exit`.

## Run and authenticate each server individually

Each server is a separate process. **Start the auth server first**, because the MCP servers
fetch its public keys to verify tokens. Use one terminal per server. All commands run from
the repo root; `S` is just shorthand for the command prefix:

```bash
S="uv run --project src/projects/mcp-demo/server python src/projects/mcp-demo/server/main.py"
```

| Step | Terminal | Command | Listens on | Scope needed |
|---|---|---|---|---|
| 1 | auth | `$S auth` | `http://127.0.0.1:9000` | — |
| 2 | weather | `$S weather` | `http://127.0.0.1:8001/mcp` | `weather:read` |
| 3 | docs | `$S docs` | `http://127.0.0.1:8002/mcp` | `docs:read` (+ `docs:write` for `ingest_documents`) |
| 4 | sql | `$S sql` | `http://127.0.0.1:8003/mcp` | `sql:read` |

You can run any subset. The client skips servers that aren't running. Stop a server with
Ctrl-C in its terminal. Ports are set in `server/.env`.

Check a server is up (no auth needed): `curl http://127.0.0.1:8001/health`

### Get a token for a server

Tokens are **bound to one server** (the JWT `aud` is that server's URL) and expire after
`TOKEN_TTL_SECONDS` (300 s by default). Get one per server:

```bash
WEATHER_TOKEN=$($S token --client demo-agent --server weather)
DOCS_TOKEN=$($S token --client demo-agent --server docs)
SQL_TOKEN=$($S token --client demo-agent --server sql)
# other clients: --client readonly-weather (weather only) | --client docs-admin (docs read + write)
```

This is the raw OAuth request that `token` (and the client's `TokenManager`) sends:

```bash
curl -s -u demo-agent:<DEMO_AGENT_SECRET from server/.env> \
     -d grant_type=client_credentials \
     -d resource=http://127.0.0.1:8003/mcp \
     http://127.0.0.1:9000/token
# → {"access_token":"eyJ...","token_type":"Bearer","expires_in":300,"scope":"sql:read"}
```

### Call a server with the token

Send the token as `Authorization: Bearer <token>` on every MCP request:

```bash
# MCP initialize over Streamable HTTP → 200
curl -s -i -X POST http://127.0.0.1:8003/mcp \
  -H "Authorization: Bearer $SQL_TOKEN" \
  -H "content-type: application/json" -H "accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'

# no token → 401, and the WWW-Authenticate header points to the protected-resource metadata
curl -s -i -X POST http://127.0.0.1:8003/mcp -H "content-type: application/json" -d '{}'
curl -s http://127.0.0.1:8003/.well-known/oauth-protected-resource/mcp   # → which auth server to use
```

For real tool calls, use MCP Inspector (below) or `client/protocol_demo.py`, which handle the
MCP session for you.

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Auth server not reachable` | Start `$S auth` first |
| `invalid_client` | Secret mismatch: `client/.env` `MCP_CLIENT_SECRET` must equal `server/.env` `DEMO_AGENT_SECRET` |
| 401 with a token that worked before | Token expired (5 min) or it was issued for another server. Get a new one with the right `--server` |
| 403 `insufficient_scope` | That client lacks the scope. Use `--client demo-agent` (or `docs-admin` for ingest) |
| `Database not found` / `No documents are indexed` | Run `$S setup` once |
| `address already in use` | A previous server is still running: `pkill -f "mcp-demo/server/main.py"` |

## Validate the servers with MCP Inspector

Inspector needs Node 22+ (`brew install node`). Start the servers first.

```bash
# 1. get a token (prints the JWT; the header line goes to stderr)
TOKEN=$(uv run --project src/projects/mcp-demo/server python src/projects/mcp-demo/server/main.py token --client demo-agent --server weather)

# 2a. UI
npx @modelcontextprotocol/inspector
#   Transport: Streamable HTTP   URL: http://127.0.0.1:8001/mcp
#   Authentication → Bearer token: paste $TOKEN   → Connect
#   Tools tab: list, run get_forecast {city: "Pune", days: 3}, see structuredContent + outputSchema
#   Prompts tab: travel_weather_brief.  Repeat with --server docs (:8002) / sql (:8003) tokens.

# 2b. CLI (scriptable)
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8001/mcp --transport http \
    --header "Authorization: Bearer $TOKEN" --method tools/list
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8001/mcp --transport http \
    --header "Authorization: Bearer $TOKEN" --method tools/call --tool-name get_current_weather --tool-arg city=Mumbai
```

A token is bound to one server, so get a new one with `--server docs` or `--server sql` for
the other ports. Tokens last 5 minutes (`TOKEN_TTL_SECONDS`).

Negative checks to show:

| Try | Expect |
|---|---|
| Connect with no token | 401 |
| Weather token on :8003 | 401 (wrong audience) |
| `token --client readonly-weather --server sql`, then connect to :8003 | 403 `insufficient_scope` |
| `ingest_documents` with a demo-agent docs token | tool error: needs `docs:write` |
| `run_sql_query` with `DROP TABLE orders` | tool error: read-only |

Inspector's "Open Auth Settings" OAuth flow expects a browser login (authorization code),
which this demo auth server deliberately doesn't implement. Use the **Bearer token** field.

With no token, Inspector's `--cli` mode follows the 401's `resource_metadata` link and tries
interactive OAuth ("requires a TTY"). That is the discovery flow working. To see the raw 401,
run `curl -i -X POST http://127.0.0.1:8003/mcp`. With a `readonly-weather` token, the CLI
reports `Insufficient scope`. Tool errors print the result and then a `tool_is_error`
summary line.

## LangSmith

Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` in `client/.env`.
Each turn becomes a trace named `mcp-agent-turn`, and all turns in a chat share a `thread_id`.
In a trace you can see:
- the skills list in the system prompt
- the `read_file /skills/<name>/SKILL.md` call that activates a skill
- each MCP tool call (`weather_*`, `docs_*`, `sql_*`) with its arguments and structured result

## Tests (no LLM)

```bash
uv run --project src/projects/mcp-demo/server pytest -q src/projects/mcp-demo/server/tests
```

The tests cover:
- token issuance rules
- 401 for missing, bad, expired, wrong-audience and wrong-issuer tokens
- 403 for a missing scope
- protected-resource metadata
- every SQL write path rejected
- document retrieval with citations
- weather structured output and its error paths

## Going to production

- Replace `auth_server/` with a real IdP (Auth0, Okta, Keycloak or Entra). The resource servers
  only need its JWKS URL and issuer.
- On the client, `mcp.client.auth.ClientCredentialsOAuthProvider` can discover the auth server
  from the `WWW-Authenticate` / protected-resource metadata instead of reading `AUTH_URL`.
- Serve over HTTPS, keep secrets in a vault, and add rate limiting per `client_id`.
