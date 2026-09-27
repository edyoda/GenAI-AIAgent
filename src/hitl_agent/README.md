# Human-in-the-Loop Agent — LangChain · Groq / OpenAI · Langfuse

A working agent with three tools where risky actions pause for a human decision before they
run. Switch between Groq, OpenAI, or any OpenAI-compatible server with one setting.

| Tool | What it does | Human review |
|---|---|---|
| `get_weather(city)` | Live weather via Open-Meteo (no key needed) | None — runs automatically |
| `calculate(expression)` | Safe arithmetic (no `eval`) | approve / reject |
| `send_email(to, subject, body)` | Simulated send, written to `outbox.jsonl` | approve / **edit** / reject |

## Quick start

```bash
cp .env.example .env        # add your keys
python main.py
```

Try:
- `what's the weather in Bengaluru?` → runs straight through
- `what is 17.5% of 2340?` → pauses, press `a` to approve
- `email the Mumbai weather to ops@example.com` → weather runs, email pauses; `e` to change the recipient, `r` to reject

In chat: `/new` starts a fresh conversation, `exit` quits.

## Switching models

Set `LLM_MODEL` in `.env` as `provider:model`, or override per run with `--model`:

| Target | Setting |
|---|---|
| Groq (default) | `LLM_MODEL=groq:openai/gpt-oss-120b` |
| Groq, Llama | `LLM_MODEL=groq:llama-3.3-70b-versatile` |
| OpenAI | `LLM_MODEL=openai:gpt-4.1-mini` |
| Any OpenAI-compatible API (Ollama, vLLM, LM Studio, OpenRouter…) | `LLM_MODEL=openai:<model>` + `LLM_BASE_URL=...` (+ `LLM_API_KEY` if needed) |

```bash
python main.py --model openai:gpt-4.1-mini
```

Optional: `LLM_FALLBACK_MODELS=groq:llama-3.3-70b-versatile` automatically retries on a
backup model if the primary errors — you can even mix providers.

## How it works

```
user ─▶ agent (LLM) ─▶ proposes tool call(s)
                          │
        HumanInTheLoopMiddleware checks HITL_POLICY
        ├─ False ─────────▶ tool runs
        └─ review needed ─▶ graph PAUSES (interrupt); state saved by the checkpointer
                              │
                    human: approve | edit | reject
                              │
        agent.stream(Command(resume={"decisions": [...]}))  (same thread_id)
        ├─ approve ─▶ tool runs as proposed
        ├─ edit    ─▶ tool runs with the human's arguments
        └─ reject  ─▶ tool skipped; model told the reason
```

Middleware stack (`agent.py`):

| Middleware | Why |
|---|---|
| `HumanInTheLoopMiddleware` | Per-tool review policy (`HITL_POLICY`) |
| `ToolRetryMiddleware` | Retries flaky `get_weather` calls with backoff; on final failure the model gets an error message instead of the app crashing |
| `ModelRetryMiddleware` | Retries rate limits / timeouts from the LLM API |
| `ModelCallLimitMiddleware` | Stops runaway tool loops (`MAX_MODEL_CALLS`, default 10) |
| `ModelFallbackMiddleware` | Only if `LLM_FALLBACK_MODELS` is set |

Parallel tool calls are handled: if the model calls weather and two emails at once, the
weather runs and both emails come to you for review together.

To change what needs approval, edit `HITL_POLICY` in `agent.py`. The in-memory checkpointer
is fine for a single process; swap in a SQLite/Postgres saver to resume paused runs after a
restart or from a web UI.

## Langfuse tracing

- Every LLM and tool call is traced through `langfuse.langchain.CallbackHandler`.
- Each chat turn is one trace (`hitl-agent-turn`), pause and resume included; a conversation is one **session**.
- Traces are tagged with the provider and carry the model name in metadata, so you can compare Groq vs OpenAI runs.
- Each human decision is an event (`human-review:<tool>`) and a categorical score (`hitl_<tool>` = approve/edit/reject).
- Without `LANGFUSE_*` keys the agent still runs, just untraced.


## Files

| File | Purpose |
|---|---|
| `main.py` | Interactive CLI, streaming tool activity, HITL resume loop, Langfuse trace/session/scores |
| `agent.py` | Agent, HITL policy, middleware stack |
| `models.py` | `provider:model` factory for Groq / OpenAI / OpenAI-compatible |
| `tools.py` | The three tools |
