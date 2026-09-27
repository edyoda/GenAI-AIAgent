"""Interactive Human-in-the-Loop agent (LangChain + Groq/OpenAI + Langfuse).

Run:   python main.py                              # pick a model at startup (Enter = .env)
       python main.py --model openai:gpt-4.1-mini    # skip the picker, use this model
       python main.py -y                           # skip the picker, use LLM_MODEL from .env
       python -m hitl_agent.main ...               # same, from src/
Chat commands:  /model [spec]  switch model (keeps history)  |  /new  fresh conversation
                /help  |  exit  quit

Tracing: each chat turn is one Langfuse trace (pause + resume included); all turns of a
conversation share one Langfuse session; every human decision is an event + a score.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

load_dotenv()

if __package__ in (None, ""):  # run as a file (IDE ▶ button / `python main.py`)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "hitl_agent"

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from .agent import build_agent, get_langfuse_handler  # noqa: E402  (after load_dotenv)
from .models import model_spec  # noqa: E402

# Shown in the model picker; any other "provider:model" string can be typed in
MODEL_PRESETS = [
    "groq:openai/gpt-oss-120b",
    "groq:llama-3.3-70b-versatile",
    "openai:gpt-4.1-mini",
]

HELP = ("  /model          pick a model from the list\n"
        "  /model <spec|n> switch to provider:model or preset n (conversation is kept)\n"
        "  /new            start a fresh conversation\n"
        "  exit            quit")

# A decider gets one paused action + its allowed decisions and returns a decision dict
Decider = Callable[[dict, list[str]], dict]


# --------------------------------------------------------------------------- #
# Human reviewer in the terminal
# --------------------------------------------------------------------------- #
def _parse_value(raw: str, original):
    """Keep strings as strings; for non-string args accept JSON (numbers, lists, ...)."""
    if isinstance(original, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def terminal_decider(action: dict, allowed: list[str]) -> dict:
    print("\n  ┌─ ⏸  HUMAN REVIEW ─────────────────────────────────────")
    print(f"  │ {action.get('description', '').splitlines()[0]}")
    print(f"  │ tool: {action['name']}")
    for k, v in action["args"].items():
        print(f"  │   {k}: {v}")
    print("  └────────────────────────────────────────────────────────")
    keys = {d[0]: d for d in allowed}
    prompt = " / ".join(f"[{d[0]}]{d[1:]}" for d in allowed)
    while True:
        decision = keys.get(input(f"  {prompt}: ").strip().lower()[:1])
        if decision == "approve":
            return {"type": "approve"}
        if decision == "reject":
            reason = input("  reason (optional): ").strip()
            return {"type": "reject", **({"message": reason} if reason else {})}
        if decision == "edit":
            print("  (Enter keeps the current value)")
            args = {}
            for k, v in action["args"].items():
                raw = input(f"  {k} [{v}]: ").strip()
                args[k] = _parse_value(raw, v) if raw else v
            return {"type": "edit", "edited_action": {"name": action["name"], "args": args}}


# --------------------------------------------------------------------------- #
# One chat turn: stream -> (interrupt -> human decides -> resume)* -> final answer
# --------------------------------------------------------------------------- #
def _stream(agent, payload, config, verbose: bool, seen: set[str]):
    """Stream graph updates, print tool activity live, return pending interrupts."""
    interrupts = []
    for update in agent.stream(payload, config=config, stream_mode="updates"):
        for node, data in update.items():
            if node == "__interrupt__":
                interrupts.extend(data)
                continue
            if not verbose or not isinstance(data, dict):
                continue
            for msg in data.get("messages", []):
                if msg.id in seen:
                    continue
                seen.add(msg.id)
                if isinstance(msg, AIMessage) and node == "model":
                    for tc in msg.tool_calls:
                        print(f"  🔧 {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})")
                elif isinstance(msg, ToolMessage):
                    # edited calls carry a reviewer notice for the model; show only the result
                    shown = str(msg.content).strip().splitlines()[-1]
                    print(f"  ↳ {msg.name}: {shown[:160]}")
    return interrupts


def run_turn(agent, thread_id: str, user_text: str, decide: Decider,
             verbose: bool = True) -> str:
    handler = get_langfuse_handler()
    lf = None
    stack = contextlib.ExitStack()
    if handler:
        from langfuse import get_client, propagate_attributes

        lf = get_client()
        stack.enter_context(propagate_attributes(
            session_id=thread_id, trace_name="hitl-agent-turn",
            tags=["hitl-demo", model_spec().split(":")[0]],
            metadata={"model": model_spec()}))
        span = stack.enter_context(lf.start_as_current_observation(
            name="hitl-agent-turn", as_type="agent", input=user_text))

    config = {"configurable": {"thread_id": thread_id},
              "callbacks": [handler] if handler else []}
    seen: set[str] = set()

    with stack:
        interrupts = _stream(agent, {"messages": [{"role": "user", "content": user_text}]},
                             config, verbose, seen)
        while interrupts:  # the agent is paused, waiting for a human
            request = interrupts[0].value  # HITLRequest (all paused calls of this step)
            allowed = {rc["action_name"]: rc["allowed_decisions"]
                       for rc in request["review_configs"]}
            decisions = []
            for action in request["action_requests"]:  # one decision per call, in order
                decision = decide(action, allowed[action["name"]])
                decisions.append(decision)
                if verbose:
                    print(f"  → {decision['type']}")
                if lf:
                    lf.create_event(name=f"human-review:{action['name']}",
                                    input={"tool": action["name"], "args": action["args"]},
                                    output=decision)
                    lf.score_current_trace(name=f"hitl_{action['name']}",
                                           value=decision["type"], data_type="CATEGORICAL",
                                           comment=decision.get("message"))
            interrupts = _stream(agent, Command(resume={"decisions": decisions}),
                                 config, verbose, seen)

        messages = agent.get_state(config).values["messages"]
        answer = messages[-1].content if messages else ""
        if isinstance(answer, list):  # some providers return content blocks
            answer = "".join(b.get("text", "") for b in answer if isinstance(b, dict))
        if lf:
            span.update(output=answer)

    if lf:
        lf.flush()
    return answer


# --------------------------------------------------------------------------- #
# Model selection: CLI flag, startup picker, or /model mid-chat
# --------------------------------------------------------------------------- #
def pick_model(current: str) -> str:
    """Numbered menu of presets; Enter keeps `current`, a typed provider:model is accepted."""
    print("  Models:")
    for i, spec in enumerate(MODEL_PRESETS, 1):
        print(f"   {i}. {spec}{'   ← current' if spec == current else ''}")
    while True:
        try:
            raw = input(f"  pick 1-{len(MODEL_PRESETS)} or type provider:model "
                        f"[Enter = {current}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return current
        if not raw:
            return current
        if raw.isdigit() and 1 <= int(raw) <= len(MODEL_PRESETS):
            return MODEL_PRESETS[int(raw) - 1]
        if ":" in raw:
            return raw
        print("  ⚠ enter a number from the list or provider:model")


def load_agent(spec: str, checkpointer):
    """Build the agent for `spec`; on failure (bad spec, missing key) restore LLM_MODEL."""
    previous = os.environ.get("LLM_MODEL")
    os.environ["LLM_MODEL"] = spec
    try:
        return build_agent(checkpointer=checkpointer)
    except Exception:
        if previous is None:
            os.environ.pop("LLM_MODEL", None)
        else:
            os.environ["LLM_MODEL"] = previous
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Human-in-the-loop agent")
    parser.add_argument("--model", help="provider:model, e.g. groq:llama-3.3-70b-versatile "
                                        "or openai:gpt-4.1-mini (overrides LLM_MODEL, skips "
                                        "the picker)")
    parser.add_argument("-y", "--no-prompt", action="store_true",
                        help="don't ask for a model at startup; use LLM_MODEL from .env")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="hide live tool-call activity")
    args = parser.parse_args()

    # one checkpointer for the whole process, so /model keeps the conversation
    checkpointer = InMemorySaver()
    interactive = sys.stdin.isatty() and not args.no_prompt
    spec = args.model or (pick_model(model_spec()) if interactive else model_spec())
    while True:
        try:
            agent = load_agent(spec, checkpointer)
            break
        except Exception as e:
            print(f"  ⚠ {type(e).__name__}: {e}")
            if not interactive:
                raise SystemExit(1)
            spec = pick_model(model_spec())

    thread_id = f"hitl-{uuid.uuid4().hex[:8]}"
    tracing = "on" if get_langfuse_handler() else "off (no LANGFUSE_* keys)"
    base = f" @ {os.environ['LLM_BASE_URL']}" if os.getenv("LLM_BASE_URL") else ""
    print(f"HITL agent  model={model_spec()}{base}  langfuse={tracing}  session={thread_id}")
    print("Try: 'weather in Bengaluru' · 'what is 17.5% of 2340?' · "
          "'email the Mumbai weather to ops@example.com'   (/model · /new · /help · exit)\n")

    while True:
        try:
            user_text = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_text.lower() in {"exit", "quit"}:
            break
        if user_text == "/help":
            print(HELP + "\n")
            continue
        if user_text == "/model" or user_text.startswith("/model "):
            spec = user_text[len("/model"):].strip() or pick_model(model_spec())
            if spec.isdigit() and 1 <= int(spec) <= len(MODEL_PRESETS):  # /model 3
                spec = MODEL_PRESETS[int(spec) - 1]
            if spec == model_spec():
                print(f"  model unchanged: {spec}\n")
                continue
            try:
                agent = load_agent(spec, checkpointer)
                print(f"  model → {model_spec()}  (same conversation: {thread_id})\n")
            except Exception as e:
                print(f"  ⚠ {type(e).__name__}: {e}  (still on {model_spec()})\n")
            continue
        if user_text == "/new":
            thread_id = f"hitl-{uuid.uuid4().hex[:8]}"
            print(f"  new conversation: {thread_id}\n")
            continue
        if user_text:
            try:
                print(f"\nagent › {run_turn(agent, thread_id, user_text, terminal_decider, verbose=not args.quiet)}\n")
            except Exception as e:  # keep the chat alive on provider/API errors
                print(f"\n  ⚠ {type(e).__name__}: {e}\n")

    if get_langfuse_handler():
        from langfuse import get_client

        get_client().shutdown()


if __name__ == "__main__":
    main()
