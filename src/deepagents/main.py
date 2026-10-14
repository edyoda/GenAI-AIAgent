"""Interactive deep agent (LangChain deepagents + weather / Tavily / calculator + LangSmith).

Run from the repo root:
    uv run --project src/deepagents python src/deepagents/main.py
    uv run --project src/deepagents python src/deepagents/main.py --once "Weather in Pune for 3 days?"
    uv run --project src/deepagents python src/deepagents/main.py --model groq:openai/gpt-oss-120b
Chat commands:  /todos  |  /files [path]  |  /tools  |  /new  |  exit

Tracing: set LANGSMITH_TRACING=true + LANGSMITH_API_KEY in .env. Each chat turn is one
LangSmith trace; all turns of a conversation share a thread_id (LangSmith "Threads" view).
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")  # resolved from this file, so it works from any cwd

from agent import build_agent  # noqa: E402  (after load_dotenv)
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from models import KEY_ENV, model_spec  # noqa: E402
from tools import build_tools  # noqa: E402

HELP = ("  /todos         show the agent's current plan\n"
        "  /files [path]  list files the agent wrote, or print one\n"
        "  /tools         list the custom tools\n"
        "  /new           start a fresh conversation\n"
        "  exit           quit")

TODO_ICON = {"pending": "○", "in_progress": "◐", "completed": "●"}


def tracing_enabled() -> bool:
    return (os.getenv("LANGSMITH_TRACING", "").lower() == "true"
            and bool(os.getenv("LANGSMITH_API_KEY")))


def _api_hint(err: Exception) -> str:
    provider = model_spec().split(":", 1)[0].lower()
    key = KEY_ENV.get(provider, "LLM_API_KEY")
    extra = " / TAVILY_API_KEY" + (" / LANGSMITH_API_KEY" if tracing_enabled() else "")
    return (f"  ⚠ API call failed ({type(err).__name__}: {err})\n"
            f"    check {key}{extra} in {BASE_DIR / '.env'}")


def _config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        # LangSmith: name each trace, and group a conversation's turns into one thread
        "run_name": "deep-agent-turn",
        "tags": ["deepagents-demo", model_spec().split(":")[0]],
        "metadata": {"thread_id": thread_id, "model": model_spec()},
        "recursion_limit": 100,
    }


def _short(args: dict, limit: int = 140) -> str:
    text = json.dumps(args, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# One chat turn: stream updates (incl. subagents), show activity live, return the answer
# --------------------------------------------------------------------------- #
def run_turn(agent, thread_id: str, user_text: str, verbose: bool = True) -> str:
    answer = ""
    for namespace, update in agent.stream({"messages": [{"role": "user", "content": user_text}]},
                                          config=_config(thread_id), stream_mode="updates",
                                          subgraphs=True):
        in_subagent = bool(namespace)  # () for the main agent, non-empty inside a `task` subagent
        indent = "      " if in_subagent else "  "
        for node, data in update.items():
            if not isinstance(data, dict):
                continue
            messages = data.get("messages")
            if not isinstance(messages, list):  # e.g. summarization's Overwrite wrapper
                continue
            for msg in messages:
                if isinstance(msg, AIMessage) and node == "model":
                    if verbose:
                        for tc in msg.tool_calls:
                            print(indent + _describe_call(tc["name"], tc["args"]))
                    if not msg.tool_calls and not in_subagent:
                        answer = msg.text
                elif isinstance(msg, ToolMessage) and verbose and msg.status == "error":
                    print(f"{indent}↳ {msg.name} error: {str(msg.content)[:160]}")
    return answer


def _describe_call(name: str, args: dict) -> str:
    if name == "write_todos":
        todos = args.get("todos", [])
        lines = [f"📝 plan ({len(todos)} steps)"]
        lines += [f"     {TODO_ICON.get(t.get('status'), '?')} {t.get('content', '')}" for t in todos]
        return "\n  ".join(lines)
    if name == "task":
        return f"🤖 subagent {args.get('subagent_type', '?')}: {args.get('description', '')[:120]}"
    if name in {"write_file", "edit_file"}:
        return f"💾 {name} {args.get('file_path', '')}"
    if name == "web_search":
        return f"🔎 web_search {args.get('query', '')!r}"
    return f"🔧 {name}({_short(args)})"


# --------------------------------------------------------------------------- #
# Inspect the thread's state (no model call)
# --------------------------------------------------------------------------- #
def show_todos(agent, thread_id: str) -> None:
    todos = agent.get_state(_config(thread_id)).values.get("todos") or []
    if not todos:
        print("  (no plan yet)\n")
        return
    for t in todos:
        print(f"  {TODO_ICON.get(t['status'], '?')} {t['content']}")
    print()


def show_files(agent, thread_id: str, path: str = "") -> None:
    files = agent.get_state(_config(thread_id)).values.get("files") or {}
    if not files:
        print("  (no files yet)\n")
    elif path:
        f = files.get(path)
        if f is None:
            print(f"  no such file: {path}\n")
        else:
            content = f.get("content", "")
            print("\n".join(content) if isinstance(content, list) else content, "\n")
    else:
        print("  " + "\n  ".join(sorted(files)) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deep agent with weather, Tavily web search and calculator tools")
    parser.add_argument("--model", help="provider:model, e.g. openai:gpt-4.1-mini (overrides LLM_MODEL)")
    parser.add_argument("--once", metavar="PROMPT", help="run a single prompt and exit")
    parser.add_argument("-q", "--quiet", action="store_true", help="hide live tool-call activity")
    args = parser.parse_args()
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    try:
        agent = build_agent()
    except Exception as e:  # bad spec or missing key
        raise SystemExit(f"  ⚠ {type(e).__name__}: {e}")

    tool_names = [t.name for t in build_tools()]
    thread_id = f"deep-{uuid.uuid4().hex[:8]}"
    tracing = (f"on (project={os.getenv('LANGSMITH_PROJECT', 'default')})"
               if tracing_enabled() else "off (set LANGSMITH_TRACING + LANGSMITH_API_KEY)")
    print(f"Deep agent  model={model_spec()}  langsmith={tracing}  thread={thread_id}")
    print(f"Custom tools: {', '.join(tool_names)}")
    if "web_search" not in tool_names:
        print("  ⚠ TAVILY_API_KEY not set: web_search and research-agent are disabled")
    print()

    try:
        if args.once:
            try:
                print(f"agent › {run_turn(agent, thread_id, args.once, verbose=not args.quiet)}")
            except Exception as e:
                raise SystemExit(_api_hint(e))
            return

        print("Try: 'Weather in Pune for the next 3 days and what to pack?' · "
              "'What is 18% GST on 74,999 INR?' · "
              "'Compare the latest LangGraph and CrewAI releases and save a summary to /notes/frameworks.md'"
              "   (/help · exit)\n")
        while True:
            try:
                user_text = input("you › ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if user_text.lower() in {"exit", "quit"}:
                break
            if user_text == "/help":
                print(HELP + "\n")
            elif user_text == "/todos":
                show_todos(agent, thread_id)
            elif user_text.startswith("/files"):
                show_files(agent, thread_id, user_text.removeprefix("/files").strip())
            elif user_text == "/tools":
                print("  " + "\n  ".join(tool_names) + "\n")
            elif user_text == "/new":
                thread_id = f"deep-{uuid.uuid4().hex[:8]}"
                print(f"  new conversation: {thread_id}\n")
            elif user_text:
                try:
                    print(f"\nagent › {run_turn(agent, thread_id, user_text, verbose=not args.quiet)}\n")
                except Exception as e:  # keep the chat alive on provider/API errors
                    print(f"\n{_api_hint(e)}\n")
    finally:
        if tracing_enabled():  # flush pending traces before the process exits
            from langchain_core.tracers.langchain import wait_for_all_tracers

            wait_for_all_tracers()


if __name__ == "__main__":
    main()
