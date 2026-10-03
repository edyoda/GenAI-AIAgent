---
name: meeting-summary
description: Turn raw meeting transcripts or notes into actionable outcomes. Use when the user asks to summarize a meeting, call, standup or transcript, or to extract decisions, action items, owners, due dates, risks, blockers or items needing leadership attention.
---

# Meeting Summary Expert

Transform raw meeting notes into a structured summary that a busy stakeholder can act on
in under two minutes.

## Workflow

1. **Find the transcript.** If the user gave a path, `read_file` it. Otherwise run `ls /data`
   and pick the matching transcript (ask if several could match).
2. **Load the output template:** `read_file /skills/meeting-summary/template.md`.
3. **Extract**, reading the whole transcript before writing:
   - Executive summary: purpose, overall status, and the single most important takeaway.
   - Key decisions that were made (not just discussed).
   - Action items, each with an **owner** and a **due date**.
   - Risks and blockers, with their impact on deadlines.
   - Items needing leadership attention (escalations, resourcing, scope or date trade-offs).
4. **Fill the template** exactly, in structured markdown.

## Rules

- Use only facts stated in the transcript. If an owner or due date is not stated, write
  **Not stated**. Never guess.
- Attribute statements to speakers when it matters ("Mike: auth fix needs one more week").
- Convert relative dates ("next Friday") only if the meeting date is known; otherwise
  keep them as said.
- Keep the executive summary to 3–5 sentences.
