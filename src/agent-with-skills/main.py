"""Interactive agent with tools + skills (LangChain + deepagents skills + LangSmith tracing).

Run from the repo root:
    uv run python src/agent-with-skills/main.py                      # chat
    uv run python src/agent-with-skills/main.py --once "Summarize the meeting in /data/meeting-transcript.txt"
    uv run python src/agent-with-skills/main.py --model groq:openai/gpt-oss-120b
Chat commands:  /skills  list skills  |  /new  fresh conversation  |  exit  quit

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

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

from agent import build_agent, build_backend  # noqa: E402  (after load_dotenv)
from models import KEY_ENV, model_spec  # noqa: E402

HELP = ("  /skills  list available skills\n"
        "  /new     start a fresh conversation\n"
        "  exit     quit")


def tracing_enabled() -> bool:
    return (os.getenv("LANGSMITH_TRACING", "").lower() == "true"
            and bool(os.getenv("LANGSMITH_API_KEY")))


def list_skills() -> list[str]:
    """Skill folder names in the sandbox (no model call)."""
    entries = build_backend().ls("/skills/").entries or []
    return [Path(e["path"].rstrip("/")).name for e in entries if e.get("is_dir")]


def _api_hint(err: Exception) -> str:
    provider = model_spec().split(":", 1)[0].lower()
    key = KEY_ENV.get(provider, "LLM_API_KEY")
    extra = " / LANGSMITH_API_KEY" if tracing_enabled() else ""
    return (f"  ⚠ API call failed ({type(err).__name__}: {err})\n"
            f"    check {key}{extra} in {BASE_DIR / '.env'}")


# --------------------------------------------------------------------------- #
# One chat turn: stream updates, show tool calls live, return the final answer
# --------------------------------------------------------------------------- #
def run_turn(agent, thread_id: str, user_text: str, verbose: bool = True) -> str:
    config = {
        "configurable": {"thread_id": thread_id},
        # LangSmith: name each trace, and group a conversation's turns into one thread
        "run_name": "skills-agent-turn",
        "tags": ["skills-demo", model_spec().split(":")[0]],
        "metadata": {"thread_id": thread_id, "model": model_spec()},
    }
    answer = ""
    for update in agent.stream({"messages": [{"role": "user", "content": user_text}]},
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
                                print(f"  🔧 {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})")
                    if not msg.tool_calls:
                        answer = msg.text
                elif isinstance(msg, ToolMessage) and verbose and msg.status == "error":
                    print(f"  ↳ {msg.name} error: {str(msg.content)[:160]}")
    return answer


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent with tools (get_weather) and skills (meeting summary, resume evaluator)")
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

    thread_id = f"skills-{uuid.uuid4().hex[:8]}"
    tracing = (f"on (project={os.getenv('LANGSMITH_PROJECT', 'default')})"
               if tracing_enabled() else "off (set LANGSMITH_TRACING + LANGSMITH_API_KEY)")
    print(f"Skills agent  model={model_spec()}  langsmith={tracing}  thread={thread_id}")
    print(f"Skills: {', '.join(list_skills()) or 'none found'}\n")

    try:
        if args.once:
            try:
                print(f"agent › {run_turn(agent, thread_id, args.once, verbose=not args.quiet)}")
            except Exception as e:
                raise SystemExit(_api_hint(e))
            return

        print("Try: 'Summarize the meeting in /data/meeting-transcript.txt' · "
              "'Evaluate the candidate resume against the senior backend role' · "
              "'What's the weather in Bengaluru?'   (/skills · /new · exit)\n")
        while True:
            try:
                user_text = input("you › ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if user_text.lower() in {"exit", "quit"}:
                break
            if user_text == "/help":
                print(HELP + "\n")
            elif user_text == "/skills":
                print("  " + "\n  ".join(list_skills()) + "\n")
            elif user_text == "/new":
                thread_id = f"skills-{uuid.uuid4().hex[:8]}"
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
