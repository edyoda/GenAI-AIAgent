"""Builds the client agent: a ReAct agent whose tools come from remote MCP servers, plus skills.

Tools   = whatever the connected MCP servers expose (weather_*, docs_*, sql_*), loaded at startup
Skills  = sandbox/skills/<name>/SKILL.md, read-only via ls/read_file (only name + description
          are in the system prompt; the agent reads the full SKILL.md when a request matches)
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.skills import SkillsMiddleware
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from models import build_model

BASE_DIR = Path(__file__).resolve().parent
SANDBOX_DIR = BASE_DIR / "sandbox"  # the model's entire filesystem: /skills/...

SYSTEM_PROMPT = """# Role
You are a helpful assistant connected to remote MCP servers: weather (live conditions,
forecasts, air quality), docs (search over company documents) and sql (a read-only retail
sales database). You also have skills with step-by-step procedures for common tasks.

# Task
- Understand the request, then:
  1. If it matches one or more skills, your FIRST action must be `read_file` on each matching
     SKILL.md (before any MCP tool), then follow its workflow and output format:
     - numbers / trends / rankings from the sales database -> /skills/sql-analyst/SKILL.md
     - what a company policy or product document says       -> /skills/document-qa/SKILL.md
     - weather, forecast, air quality, packing              -> /skills/weather-briefing/SKILL.md
  2. Only if no skill matches, call the relevant MCP tools directly, or answer from your own
     knowledge if no tool is needed.
- Return a clear, well-structured answer.

# Instructions
- Base facts on tool results. Never invent weather readings, policy details or numbers.
- If a tool returns an error, read it: fix your arguments and retry once if you can (e.g. a bad
  SQL column), otherwise tell the user plainly what failed. Do not retry authorization errors.
- If a server you need is unavailable (see below), say so instead of guessing.
- Ask a clarifying question when essential information is missing.
- Keep responses concise.

# Server status at startup
{server_status}"""


def build_backend() -> FilesystemBackend:
    return FilesystemBackend(root_dir=SANDBOX_DIR, virtual_mode=True)


def build_agent(tools: list[BaseTool], server_status: str, model: BaseChatModel | None = None,
                checkpointer=None):
    backend = build_backend()
    return create_agent(
        model=model or build_model(),
        tools=tools,
        system_prompt=SYSTEM_PROMPT.format(server_status=server_status),
        middleware=[
            SkillsMiddleware(backend=backend, sources=["/skills/"]),
            # read-only access to the skills; eviction off so nothing is ever written
            FilesystemMiddleware(backend=backend, tools=["ls", "read_file"]),
        ],
        checkpointer=checkpointer or InMemorySaver(),
        name="mcp-client-agent",
    )
