"""Builds the deep agent.

Built-in (from create_deep_agent):
    ls, read_file, write_file, edit_file, delete, glob, grep -> virtual filesystem (StateBackend: lives
                                                   in the agent's state per thread, never touches disk)
    task                                        -> delegate work to a subagent with a fresh context
    execute                                     -> shell; only works with a sandbox backend, so here it
                                                   just returns an error
    + summarization of long histories, patching of dangling tool calls

Added here:
    write_todos  (TodoListMiddleware)           -> planning: a visible todo list for multi-step tasks.
                                                   deepagents 0.7 no longer adds it by default.

Custom (tools.py):
    get_weather, calculate, web_search (Tavily)

Subagents:
    general-purpose   -> added automatically; same tools as the main agent
    research-agent    -> web research only; returns a short sourced brief
"""

from __future__ import annotations

from deepagents.backends import StateBackend
from langchain.agents.middleware import TodoListMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from models import build_model
from tools import build_tools

from deepagents import create_deep_agent

SYSTEM_PROMPT = """# Role
You are a capable research and planning assistant. You answer simple questions directly and
break larger tasks into steps.

# Tools
- `get_weather`: current weather and up to a 7-day forecast for a city.
- `calculate`: exact arithmetic. Use it for every non-trivial calculation instead of mental math.
- `web_search`: current facts, news, prices and anything you are not certain of. Cite URLs.
- `write_todos`: for tasks with 3+ steps, write a plan first and keep it updated as you go.
- Files (`write_file`, `read_file`, ...): a scratch space for notes and longer drafts, e.g.
  save research findings to `/notes/<topic>.md` and build the final answer from them.
- `task`: hand an independent sub-question to a subagent. Use `research-agent` for focused web
  research, and run independent research tasks in parallel.

# Guidelines
- Use the simplest approach that works; don't plan or delegate for one-step questions.
- Never invent facts, numbers or sources. If a tool fails, say so.
- Final answers: clear and well structured, with sources listed when you used the web.
"""

RESEARCH_SUBAGENT = {
    "name": "research-agent",
    "description": (
        "Researches one focused question on the web and returns a concise, sourced brief. "
        "Give it a single topic per call; call it several times in parallel for several topics."
    ),
    "system_prompt": (
        "You are a focused web researcher. Run 1-3 targeted `web_search` queries, use "
        "`calculate` for any numbers you derive, and reply with a brief of at most ~200 words: "
        "key findings as bullets, then a 'Sources' list of URLs. Only report what the sources "
        "say. Your reply is passed back to another agent, not shown to the user."
    ),
}


def build_agent():
    tools = build_tools()
    tool_names = {t.name for t in tools}
    subagents = []
    if "web_search" in tool_names:  # the researcher is useless without search
        subagents.append({
            **RESEARCH_SUBAGENT,
            "tools": [t for t in tools if t.name in {"web_search", "calculate"}],
        })

    return create_deep_agent(
        model=build_model(),
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        subagents=subagents,
        middleware=[TodoListMiddleware()],
        backend=StateBackend(),       # the default, made explicit: files live in agent state
        checkpointer=InMemorySaver(),  # remembers each thread's messages, todos and files
        name="deep-agent",
    )
