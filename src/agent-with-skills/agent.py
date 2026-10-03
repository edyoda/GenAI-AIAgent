"""Builds the agent: a general ReAct agent with regular tools plus on-demand skills.

Tools:
    get_weather              -> regular tool (tools.py), called directly
    ls, read_file            -> read-only access to the `sandbox/` folder next to this file

The sandbox is the model's whole filesystem:
    /skills/<name>/SKILL.md  -> skills (only name + description go into the system prompt)
    /data/...                -> inputs (transcripts, resumes, job descriptions)

It can look but never write.
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.skills import SkillsMiddleware
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from models import build_model
from tools import TOOLS

BASE_DIR = Path(__file__).resolve().parent
SANDBOX_DIR = BASE_DIR / "sandbox"  # the model's entire filesystem

SYSTEM_PROMPT = """# Role
You are a helpful assistant. You can answer general questions directly, call tools, and
apply specialised skills when a request matches one.

# Goal
Complete the user's task accurately and efficiently, using the simplest approach that works.

# Task
- Understand the user's request.
- Decide how to handle it:
  - If it matches an available skill, load that skill and follow its instructions.
  - If a tool can answer it (e.g. `get_weather` for current weather), call the tool.
  - Otherwise, answer directly from your own knowledge.
- Return the result in the format appropriate to the task.

# Instructions
- Only load a skill when the request clearly matches its description; don't force one.
- Input files (meeting transcripts, resumes, job descriptions) live under /data. Use `ls`
  to explore and `read_file` to read. You cannot create, edit or delete files; if asked to
  save something, return it in your answer instead.
- Base outputs on what you've read or what tools return; do not invent facts or results.
- Ask for clarification when essential information is missing or ambiguous.
- Prefer completing the task end-to-end rather than providing unnecessary guidance.
- Keep responses concise, clear, and well-structured."""


def build_backend() -> FilesystemBackend:
    # virtual_mode=True: paths are anchored to SANDBOX_DIR; `..`, `~` and escapes are blocked
    return FilesystemBackend(root_dir=SANDBOX_DIR, virtual_mode=True)


def build_agent(model: BaseChatModel | None = None, checkpointer=None):
    backend = build_backend()
    return create_agent(
        model=model or build_model(),
        tools=TOOLS,  # regular tools; ls + read_file come from FilesystemMiddleware
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            # 1. list /skills/*/SKILL.md (name + description) in the system prompt;
            #    the model reads the full SKILL.md only when a request matches
            SkillsMiddleware(backend=backend, sources=["/skills/"]),
            # 2. expose only ls + read_file; disable result eviction, which would write
            #    large outputs into the sandbox and break the read-only guarantee
            FilesystemMiddleware(
                backend=backend,
                tools=["ls", "read_file"],
                tool_token_limit_before_evict=None,
                human_message_token_limit_before_evict=None,
            ),
        ],
        checkpointer=checkpointer or InMemorySaver(),
        name="skills-agent",
    )
