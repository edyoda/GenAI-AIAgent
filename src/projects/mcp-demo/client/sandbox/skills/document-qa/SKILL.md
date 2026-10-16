---
name: document-qa
description: Answer questions from the company's internal documents (employee handbook, leave and remote-work rules, travel & expense policy, information security policy, product FAQ, pricing, SLA) with citations. Use whenever the user asks what a policy says, what they are entitled to, limits/caps/allowances, or product facts that would be in these documents.
---

# Document Q&A (grounded, cited)

Answer only from retrieved passages served by the `docs` MCP server, and cite them.

## Workflow
1. **Retrieve:** call `docs_get_context` with the user's question rephrased as a focused search
   query (keep key nouns: "hotel cap Pune", "parental leave weeks").
   - If the question has several parts, call it once per part.
2. **Check relevance:** if `found` is false, or the passages don't actually answer the question,
   try ONE reformulated query (synonyms, the policy name). Still nothing → say so.
3. **Need more?** If a passage is cut off, call `docs_get_chunk` with its `chunk_id`.
4. **Answer** using only the passages.

## Output format
```
<direct answer in 1–3 sentences, with [n] markers after each fact>

**Details**
- <supporting points / conditions / exceptions, each with [n]>

**Sources**
[1] <source> › <section>
[2] ...
```

## Rules
- No outside knowledge: if the documents don't say it, answer
  "The documents don't cover this." and state what they do cover, if relevant.
- Quote numbers exactly as written (amounts, currencies, days, percentages).
- Mention conditions and exceptions (approvals, deadlines, caps) — they matter most in policies.
- Never cite a source you didn't retrieve.
