"""MCP client agent: LangChain ReAct + skills, tools from 3 authenticated MCP servers.

Start the servers first (server project), then from the repo root:
    uv run --project src/projects/mcp-demo/client python src/projects/mcp-demo/client/main.py
    uv run --project src/projects/mcp-demo/client python src/projects/mcp-demo/client/main.py --once "Weather in Pune for the next 3 days?"
Chat commands:  /servers  connection + scope status | /skills | /new | exit

Tracing: LANGSMITH_TRACING=true + LANGSMITH_API_KEY in client/.env. One trace per turn; turns
of a conversation share a thread_id (LangSmith "Threads" view). MCP tool calls show up as
tool runs with their arguments and results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")  # before importing modules that read env vars

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

from agent import build_agent, build_backend  # noqa: E402
from mcp_connections import ServerStatus, connect  # noqa: E402
from models import KEY_ENV, model_spec  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="  ⚠ %(message)s")
HELP = ("  /servers  MCP server status, granted scopes, tools\n"
        "  /skills   list available skills\n"
        "  /new      start a fresh conversation\n"
        "  exit      quit")


def tracing_enabled() -> bool:
    return os.getenv("LANGSMITH_TRACING", "").lower() == "true" and bool(os.getenv("LANGSMITH_API_KEY"))


def list_skills() -> list[str]:
    entries = build_backend().ls("/skills/").entries or []
    return [Path(e["path"].rstrip("/")).name for e in entries if e.get("is_dir")]


def status_text(statuses: dict[str, ServerStatus]) -> str:
    """Also injected into the system prompt, so the model knows what is unavailable."""
    lines = []
    for s in statuses.values():
        if s.ok:
            lines.append(f"- {s.name}: connected ({len(s.tools)} tools, scope '{s.scope}')")
        else:
            lines.append(f"- {s.name}: UNAVAILABLE — {s.error}")
    return "\n".join(lines)


def _api_hint(err: Exception) -> str:
    provider = model_spec().split(":", 1)[0].lower()
    key = KEY_ENV.get(provider, "LLM_API_KEY")
    extra = " / LANGSMITH_API_KEY" if tracing_enabled() else ""
    return (f"  ⚠ LLM API call failed ({type(err).__name__}: {err})\n"
            f"    check {key}{extra} in {BASE_DIR / '.env'}")


# --------------------------------------------------------------------------- #
# One chat turn
# --------------------------------------------------------------------------- #
async def run_turn(agent, thread_id: str, user_text: str, verbose: bool = True) -> str:
    config = {
        "configurable": {"thread_id": thread_id},
        "run_name": "mcp-agent-turn",
        "tags": ["mcp-demo", model_spec().split(":")[0]],
        "metadata": {"thread_id": thread_id, "model": model_spec()},
    }
    answer = ""
    async for update in agent.astream({"messages": [{"role": "user", "content": user_text}]},
                                      config=config, stream_mode="updates"):
        for node, data in update.items():
            if not isinstance(data, dict):
                continue
            for msg in data.get("messages", []):
                if isinstance(msg, AIMessage) and node == "model":
                    if verbose:
                        for tc in msg.tool_calls:
                            path = tc["args"].get("file_path", "")
                            if tc["name"] == "read_file" and path.endswith("/SKILL.md"):
                                print(f"  📘 skill loaded: {Path(path).parent.name}")
                            else:
                                icon = "🔌" if tc["name"].split("_")[0] in ("weather", "docs", "sql") else "🔧"
                                print(f"  {icon} {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)[:200]})")
                    if not msg.tool_calls:
                        answer = msg.text
                elif isinstance(msg, ToolMessage) and verbose and msg.status == "error":
                    print(f"  ↳ {msg.name} error: {str(msg.text or msg.content)[:200]}")
    return answer


async def amain() -> None:
    parser = argparse.ArgumentParser(description="MCP client agent with skills")
    parser.add_argument("--model", help="provider:model (overrides LLM_MODEL)")
    parser.add_argument("--once", metavar="PROMPT", help="run a single prompt and exit")
    parser.add_argument("-q", "--quiet", action="store_true", help="hide live tool-call activity")
    args = parser.parse_args()
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    # 1. connect to the MCP servers (no LLM involved)
    tools, statuses, _client = await connect()
    print(f"MCP servers (client_id={os.getenv('MCP_CLIENT_ID', 'demo-agent')}):\n{status_text(statuses)}")
    if not tools:
        raise SystemExit("  ⚠ No MCP server available. Start them with `server/main.py all`, "
                         "and check MCP_CLIENT_SECRET in client/.env.")

    # 2. build the agent
    try:
        agent = build_agent(tools, status_text(statuses))
    except Exception as e:  # bad model spec or missing key
        raise SystemExit(f"  ⚠ {type(e).__name__}: {e}")

    thread_id = f"mcp-{uuid.uuid4().hex[:8]}"
    tracing = (f"on (project={os.getenv('LANGSMITH_PROJECT', 'default')})" if tracing_enabled() else "off")
    print(f"\nAgent  model={model_spec()}  langsmith={tracing}  thread={thread_id}")
    print(f"Skills: {', '.join(list_skills()) or 'none'}\n")

    try:
        if args.once:
            try:
                print(f"agent › {await run_turn(agent, thread_id, args.once, verbose=not args.quiet)}")
            except Exception as e:
                raise SystemExit(_api_hint(e))
            return

        print("Try: 'Weather in Pune for the next 3 days?' · 'How many days of annual leave do I get?' · "
              "'Which region had the highest revenue last quarter?'   (/servers · /skills · /new · exit)\n")
        while True:
            try:
                user_text = (await asyncio.to_thread(input, "you › ")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if user_text.lower() in {"exit", "quit"}:
                break
            if user_text == "/help":
                print(HELP + "\n")
            elif user_text == "/servers":
                for s in statuses.values():
                    print(f"  {s.name:8} {'✅' if s.ok else '❌'} {s.url}  scope='{s.scope}'  {s.error}")
                    if s.ok:
                        print(f"           tools: {', '.join(s.tools)}")
                print()
            elif user_text == "/skills":
                print("  " + "\n  ".join(list_skills()) + "\n")
            elif user_text == "/new":
                thread_id = f"mcp-{uuid.uuid4().hex[:8]}"
                print(f"  new conversation: {thread_id}\n")
            elif user_text:
                try:
                    print(f"\nagent › {await run_turn(agent, thread_id, user_text, verbose=not args.quiet)}\n")
                except Exception as e:  # keep the chat alive on LLM/provider errors
                    print(f"\n{_api_hint(e)}\n")
    finally:
        if tracing_enabled():
            from langchain_core.tracers.langchain import wait_for_all_tracers

            wait_for_all_tracers()


if __name__ == "__main__":
    asyncio.run(amain())
