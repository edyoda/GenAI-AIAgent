# Agent with Skills — LangChain · deepagents SkillsMiddleware · LangSmith

A general ReAct agent that can answer directly, call regular **tools**, and load **skills**
only when a request needs one. It shows the difference between the two:

| | Tool (`get_weather`) | Skill (`meeting-summary`, `resume-evaluator`) |
|---|---|---|
| What it is | A Python function the model calls | Instructions and files the model reads |
| Defined in | `tools.py` | `sandbox/skills/<name>/SKILL.md` |
| Cost up front | Full schema in every request | Name + description only |
| Best for | Actions and live data | Multi-step procedures, domain know-how |

Skills work through *progressive disclosure*:

1. At startup, only each skill's `name` + `description` (from `SKILL.md` frontmatter) go into
   the system prompt. That costs a few tokens per skill.
2. When a request matches a skill, the agent **reads the full `SKILL.md` itself** with `read_file`.
3. The skill can point to more files (a template or rubric), which the agent reads only when needed.

| Skill | Triggers on | Extra files it loads |
|---|---|---|
| `meeting-summary` | "summarize this meeting / extract action items" | `template.md` |
| `resume-evaluator` | "evaluate this resume against the role" | `rubric.md` |

## Safety: sandboxed and read-only

- The model can only see `sandbox/` (`FilesystemBackend(root_dir=sandbox, virtual_mode=True)`).
  To it, the sandbox is `/`, containing `/skills` and `/data`. Paths like `..` and `~`, and
  anything that resolves outside the sandbox, are rejected.
- Its only filesystem tools are `ls` and `read_file` (`FilesystemMiddleware(tools=[...])`), so it
  can't write, edit, delete or run anything. `get_weather` only makes a read-only HTTPS call to
  Open-Meteo, which needs no API key. Large-result eviction is disabled so the
  middleware never writes into the sandbox either.

```
src/agent-with-skills/
├── agent.py  main.py  models.py  tools.py  .env.example   # code — invisible to the model
└── sandbox/                                       # the model's entire world
    ├── skills/{meeting-summary,resume-evaluator}/SKILL.md (+ template.md / rubric.md)
    └── data/{meeting-transcript.txt, resumes/, jobs/}
```

## Run (from the repo root)

```bash
uv sync
cp src/agent-with-skills/.env.example src/agent-with-skills/.env   # add your keys
uv run python src/agent-with-skills/main.py
uv run python src/agent-with-skills/main.py --once "Summarize the meeting in /data/meeting-transcript.txt"
uv run python src/agent-with-skills/main.py --model groq:openai/gpt-oss-120b
```

In VS Code, use the **Skills agent** launch config. Chat commands: `/skills`, `/new`, `exit`.

Try:
- `Summarize the meeting in /data/meeting-transcript.txt`
- `Evaluate the candidate resume against the senior backend engineer role`
- `What's the weather in Bengaluru?` (calls the tool, loads no skill)
- `What can you do?` or `Explain REST vs gRPC` (answered directly, no tool or skill)

## LangSmith

Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` in `.env`. Each chat
turn becomes a trace named `skills-agent-turn`, tagged `skills-demo` plus the provider. All
turns in one conversation share a `thread_id`, so the **Threads** tab shows the whole chat.

What to point out in a trace:
- **First model call → System prompt**: the skills list injected by `SkillsMiddleware`, with
  only names and descriptions.
- **`read_file /skills/<name>/SKILL.md`**: the moment the skill is activated.
- **Further `read_file` calls** for the template, rubric and inputs, loaded only when needed.

## Add a tool

Write a `@tool` function in `tools.py` and add it to `TOOLS`.

## Add a skill

Create `sandbox/skills/<skill-name>/SKILL.md`:

```markdown
---
name: <skill-name>            # lowercase-hyphen, must match the folder name
description: What it does and WHEN to use it (this is all the model sees up front).
---
# Instructions the agent follows once it loads the skill...
```

Restart the agent. There's no code change needed.
