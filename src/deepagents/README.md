# Deep Agent — LangChain deepagents · weather · Tavily · calculator · LangSmith

A standalone deep agent built with `create_deep_agent`. It plans multi-step work, keeps notes in a
virtual filesystem, and hands focused research to subagents. On top of those built-in tools it
has three custom ones.

| Tool | Source | What it does |
|---|---|---|
| `write_todos` | `TodoListMiddleware` (added in `agent.py`) | Writes and updates a visible plan |
| `ls` `read_file` `write_file` `edit_file` `delete` `glob` `grep` | deepagents `FilesystemMiddleware` | Virtual files kept in the agent's state, per thread. Nothing is written to disk |
| `task` | deepagents `SubAgentMiddleware` | Delegates to `general-purpose` or `research-agent` |
| `execute` | deepagents | Shell commands. Needs a sandbox backend, so with `StateBackend` it only returns an error |
| `get_weather` | `tools.py` | Current weather + up to 7-day forecast (Open-Meteo, no key) |
| `calculate` | `tools.py` | Safe math via the AST: `+ - * / // % **`, `sqrt`, `log`, `pi`, … (no `eval`) |
| `web_search` | `tools.py` → `langchain_tavily.TavilySearch` | Web search with URLs. Needs `TAVILY_API_KEY` |

Subagents:
- **general-purpose** is added automatically and has the same tools as the main agent.
- **research-agent** has only `web_search` and `calculate`. It returns a sourced brief of about 200 words, so the main agent's context stays small. It is disabled when there is no Tavily key.

The agent also gets deepagents' summarization of long histories, and `InMemorySaver` keeps
messages, todos and files per `thread_id`.

## Run (from the repo root)

This folder is its own uv project with its own `.venv`, separate from the root environment.

```bash
cp src/deepagents/.env.example src/deepagents/.env      # add your keys
uv sync --project src/deepagents
uv run --project src/deepagents python src/deepagents/main.py
uv run --project src/deepagents python src/deepagents/main.py --once "What is 18% GST on 74,999 INR?"
uv run --project src/deepagents python src/deepagents/main.py --model groq:openai/gpt-oss-120b
```

Chat commands: `/todos` (current plan), `/files [path]` (list or print the virtual files),
`/tools`, `/new`, `exit`.

Try:
- `What is 18% GST on 74,999 INR?` (one `calculate` call, no plan)
- `Weather in Pune for the next 3 days and what should I pack?`
- `Compare the latest LangGraph and CrewAI releases and save a summary to /notes/frameworks.md`
  (plan → parallel `research-agent` tasks → file write → answer; then try `/files /notes/frameworks.md`)

## Files

| File | Purpose |
|---|---|
| `agent.py` | `create_deep_agent` setup: system prompt, research subagent, todo middleware, backend, checkpointer |
| `tools.py` | `get_weather`, `calculate`, Tavily `web_search` |
| `models.py` | `provider:model` factory for OpenAI / Groq / OpenAI-compatible servers |
| `main.py` | Chat REPL / `--once`. Streams the plan, tool calls and subagent activity (`subgraphs=True`), and adds LangSmith run config |

## Notes

- The folder is named `deepagents`, the same as the library. That works because it has no
  `__init__.py`, and the scripts run with this folder (not `src/`) on `sys.path`. Don't make it a
  package or run it as `python -m deepagents...` from `src/`.
- If you pass `model` as an `openai:` string, deepagents uses the Responses API. `models.py`
  passes an initialized model instead, so OpenAI-compatible servers (Ollama, vLLM, …) work too.
- To let the agent read and write real files, swap `StateBackend()` for
  `FilesystemBackend(root_dir=..., virtual_mode=True)`, as in `src/agent-with-skills`.
