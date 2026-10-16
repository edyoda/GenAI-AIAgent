---
name: sql-analyst
description: Analyse the retail sales database with SQL — revenue, orders, customers, products, categories, regions, channels, trends over time, top-N rankings, growth, margins, averages. Use when the user asks a business or data question that needs numbers from the database.
---

# SQL Analyst

Answer business questions with correct, verifiable SQL against the `sql` MCP server (SQLite,
read-only).

## Workflow
1. **Understand the schema. Never guess names.**
   - `sql_list_tables`, then `sql_describe_table` for every table you plan to use.
   - Use `sql_get_sample_rows` or `sql_profile_column` when you need to see value formats
     (e.g. status values, date format).
2. **Plan** the metric in one line before writing SQL (what is counted/summed, filters, grouping).
3. **Write ONE SELECT** (CTEs are fine). SQLite dialect: `strftime('%Y-%m', order_date)` for
   months, `ROUND(x, 2)`, no `ILIKE`.
4. **Validate** with `sql_explain_query`. If it errors, fix and re-validate.
5. **Run** with `sql_run_sql_query`. If `truncated` is true, aggregate further or add LIMIT.
6. **Sanity-check** the result: totals plausible, no unexpected NULLs, row counts make sense.
   If something looks off, investigate with one more query.

## Business definitions (use unless the user says otherwise)
- **Revenue** = `SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct / 100.0))`
- **Cost** = `SUM(oi.quantity * p.unit_cost)`; **Gross margin** = revenue − cost
- Exclude orders with `status = 'cancelled'` from revenue; mention returns separately if relevant.
- Average order value = revenue / COUNT(DISTINCT order_id).

## Output format
~~~~
## <Question restated>
**Answer:** <the key insight in 1–2 sentences, with the headline numbers>

| … result table (≤ 15 rows, formatted numbers) … |

**Notes:** assumptions, filters applied, anything surprising.

<details><summary>SQL used</summary>

```sql
<the final query>
```
</details>
~~~~

## Rules
- Every number in the answer must come from a query result. No mental arithmetic over large sets;
  compute it in SQL.
- The database is read-only; if asked to change data, explain that you can't.
- If the question is ambiguous (e.g. "last quarter" with no reference date), state the assumption
  you made (use the latest `order_date` in the data as "today").
