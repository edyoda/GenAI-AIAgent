---
name: resume-evaluator
description: Evaluate and score a candidate's resume or CV against a job description or role. Use when the user asks to screen, assess, rate, shortlist or compare a resume/CV for a job, or asks how well a candidate fits a position.
---

# Resume Evaluator

Produce an evidence-based, fair assessment of how well a resume matches a specific job.

## Workflow

1. **Find the inputs.** If the user gave paths, use them. Otherwise run `ls /data/resumes`
   and `ls /data/jobs` and pick the matching files (ask if it is ambiguous).
2. **Read the job description** with `read_file`. List its requirements in two groups:
   - **Must-have**: skills or experience stated as required.
   - **Nice-to-have**: preferred, bonus or "plus" items.
3. **Load the scoring rubric:** `read_file /skills/resume-evaluator/rubric.md`.
4. **Read the resume** with `read_file`.
5. **Map every requirement to evidence**: quote the resume line that supports it, and mark it
   Met / Partial / Missing.
6. **Score each rubric dimension** using the rubric's anchors, then compute the weighted total.

## Output format

```
# Resume Evaluation: <candidate> → <role>

## Overall: <score>/100 — <Strong Yes | Yes | Maybe | No>
<2–3 sentence verdict>

## Score Breakdown
| Dimension | Weight | Score (0–10) | Weighted | Rationale |

## Requirement Match
| Requirement | Type | Status | Evidence from resume |

## Strengths
## Gaps & Risks
## Suggested Interview Questions
<3–5 questions that probe the gaps>
```

## Rules

- Evidence only: if the resume doesn't say it, it's **Missing**. Don't infer skills from
  job titles alone.
- Fairness: ignore name, age, gender, nationality, photos, marital status and other protected
  attributes. Don't penalise career gaps without job-relevant reasons.
- Recommendation thresholds: ≥80 Strong Yes, 65–79 Yes, 50–64 Maybe, <50 No. Any unmet
  must-have caps the recommendation at **Maybe**.
