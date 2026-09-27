"""Builds the LangChain agent: HITL + retries + loop limit + optional model fallback."""

from __future__ import annotations

import os

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    ToolRetryMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver

from .models import build_fallback_models, build_model
from .tools import ALL_TOOLS

SYSTEM_PROMPT = """You are a helpful assistant with three tools:
- get_weather(city): current weather for a city
- calculate(expression): arithmetic
- send_email(to, subject, body): send an email

Rules:
- Always use calculate for arithmetic instead of doing it in your head.
- Only call send_email when the user explicitly asks to send or email something.
- Tools marked for review are checked by a human before they run. If a reviewer rejects a
  call, do not retry it; acknowledge the reason and continue. If a reviewer edited a call,
  report the result of the edited call.
- Keep answers short and concrete."""

# ---- Human-in-the-Loop policy ---------------------------------------------- #
# False -> runs automatically. dict -> execution PAUSES until a human decides.
HITL_POLICY = {
    "get_weather": False,
    "calculate": {
        "allowed_decisions": ["approve", "reject"],
        "description": "Calculator call - please sanity-check the expression",
    },
    "send_email": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "Outgoing email - review recipient, subject and body",
    },
}


def build_agent(model: BaseChatModel | None = None, checkpointer=None):
    """Create the agent.

    A checkpointer is REQUIRED for HITL: it stores the paused state so the run can resume
    after the human decides. InMemorySaver is fine for one process; swap in a SQLite or
    Postgres saver to survive restarts or resume from another process (e.g. a web UI).
    """
    middleware = [
        # 1. pause risky tool calls for a human decision
        HumanInTheLoopMiddleware(interrupt_on=HITL_POLICY),
        # 2. retry flaky network tools with exponential backoff; on final failure the model
        #    receives an error message instead of the run crashing
        ToolRetryMiddleware(tools=["get_weather"], max_retries=2, initial_delay=0.5),
        # 3. retry transient model/API errors (rate limits, timeouts)
        ModelRetryMiddleware(max_retries=2, initial_delay=1.0),
        # 4. guard against runaway tool loops
        ModelCallLimitMiddleware(run_limit=int(os.getenv("MAX_MODEL_CALLS", "10")),
                                 exit_behavior="end"),
    ]
    if model is None:  # fallbacks only apply to real models, not injected test models
        fallbacks = build_fallback_models()
        if fallbacks:
            middleware.append(ModelFallbackMiddleware(*fallbacks))

    return create_agent(
        model=model or build_model(),
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
        checkpointer=checkpointer or InMemorySaver(),
        name="hitl-demo-agent",
    )


def get_langfuse_handler():
    """Langfuse CallbackHandler if keys are configured, else None (agent still runs)."""
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return None
    from langfuse.langchain import CallbackHandler

    return CallbackHandler()  # reads LANGFUSE_PUBLIC_KEY / SECRET_KEY / BASE_URL
