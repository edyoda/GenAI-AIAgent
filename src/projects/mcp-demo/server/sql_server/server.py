"""SQL analytics MCP server (port 8003, scope sql:read) over the sample SQLite sales DB.

The model can explore the schema and run its own SELECTs, but can never change anything:
  1. the DB is opened read-only (`mode=ro`) and `PRAGMA query_only=ON`
  2. an sqlite authorizer allows only reads (no INSERT/UPDATE/DELETE/DDL/ATTACH/PRAGMA)
  3. one statement per call (sqlite3 rejects `...; DROP TABLE x`)
  4. results are capped at `max_rows`, and a query running longer than QUERY_TIMEOUT_S is aborted
"""

from __future__ import annotations

import sqlite3
import time
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from common.auth import auth_config
from common.config import DB_PATH, RESOURCE_SERVERS
from common.logs import request_logger, setup_logging

SERVER = RESOURCE_SERVERS["sql"]
log = setup_logging("sql")

QUERY_TIMEOUT_S = 5.0
READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

# a SQLite value as JSON (BLOBs are returned as hex strings)
Cell = str | int | float | None

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):  # WITH RECURSIVE
    _ALLOWED_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)


# Business meaning of columns whose name alone is ambiguous (surfaced by describe_table)
COLUMN_NOTES = {
    ("order_items", "discount_pct"): "Discount in PERCENT, 0-100 (10 means 10%). "
                                     "Line revenue = quantity * unit_price * (1 - discount_pct / 100.0).",
    ("order_items", "unit_price"): "Price per unit charged on this order, before discount.",
    ("products", "unit_price"): "Current list price; use order_items.unit_price for revenue.",
    ("products", "unit_cost"): "Cost per unit. Line cost = order_items.quantity * products.unit_cost.",
    ("orders", "status"): "completed | shipped | cancelled | returned. Exclude cancelled from revenue.",
    ("orders", "order_date"): "ISO date text 'YYYY-MM-DD'; use strftime('%Y', order_date) etc.",
}


def _authorizer(action: int, *_: Any) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def _connect(guarded: bool) -> sqlite3.Connection:
    """guarded=True for model-written SQL; False only for our own fixed metadata queries."""
    if not DB_PATH.exists():
        raise ToolError("Database not found. Run `python src/projects/mcp-demo/server/main.py seed-db` first.")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    if guarded:
        conn.set_authorizer(_authorizer)
        deadline = time.monotonic() + QUERY_TIMEOUT_S
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    return conn


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _check_table(conn: sqlite3.Connection, table: str) -> None:
    tables = _tables(conn)
    if table not in tables:  # also stops identifier injection in the f-strings below
        raise ToolError(f"Unknown table '{table}'. Available: {', '.join(tables)}")


def _run(sql: str, max_rows: int) -> tuple[list[str], list[list], bool]:
    conn = _connect(guarded=True)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description or []]
        rows = [[v.hex() if isinstance(v, bytes) else v for v in r] for r in cur.fetchmany(max_rows + 1)]
    except sqlite3.DatabaseError as e:
        msg = str(e)
        if "not authorized" in msg or "readonly" in msg:
            raise ToolError("Rejected: only read-only SELECT queries are allowed.")
        if "interrupted" in msg:
            raise ToolError(f"Query exceeded {QUERY_TIMEOUT_S:.0f}s and was stopped; add filters or LIMIT.")
        if "one statement" in msg:
            raise ToolError("Rejected: send exactly one SELECT statement per call.")
        raise ToolError(f"SQL error: {msg}")
    finally:
        conn.close()
    return cols, rows[:max_rows], len(rows) > max_rows


# --------------------------------------------------------------------------- #
# Output models
# --------------------------------------------------------------------------- #
class Column(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: bool
    references: str | None = None
    description: str | None = None


class TableInfo(BaseModel):
    table: str
    row_count: int
    columns: list[Column]


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Cell]]
    row_count: int
    truncated: bool = Field(description="True if more rows existed than max_rows")
    elapsed_ms: float


class TopValue(BaseModel):
    value: Cell
    count: int


class ColumnProfile(BaseModel):
    table: str
    column: str
    rows: int
    nulls: int
    distinct: int
    min: Cell = None
    max: Cell = None
    avg: float | None = None
    top_values: list[TopValue]


def build_server(auth: bool = True) -> MCPServer:
    mcp = MCPServer(
        "sql",
        instructions="Read-only analytics over a retail sales database (regions, customers, products, "
                     "orders, order_items). Explore the schema before writing SQL. "
                     "order_items.discount_pct is a percentage (0-100): revenue = "
                     "quantity * unit_price * (1 - discount_pct / 100.0); exclude cancelled orders.",
        middleware=[request_logger(log)],
        **(auth_config(SERVER) if auth else {}),
    )

    @mcp.tool(annotations=READ_ONLY)
    def list_tables() -> dict[str, int]:
        """All tables with their row counts."""
        conn = _connect(guarded=False)
        try:
            return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in _tables(conn)}
        finally:
            conn.close()

    @mcp.tool(annotations=READ_ONLY)
    def describe_table(table: str) -> TableInfo:
        """Columns of a table: name, type, nullability, primary key, foreign-key references and,
        for business-critical columns, a description of what the value means. Call before writing SQL."""
        conn = _connect(guarded=False)
        try:
            _check_table(conn, table)
            fks = {r[3]: f"{r[2]}.{r[4]}" for r in conn.execute(f'PRAGMA foreign_key_list("{table}")')}
            cols = [Column(name=r[1], type=r[2], nullable=not r[3], primary_key=bool(r[5]), references=fks.get(r[1]),
                           description=COLUMN_NOTES.get((table, r[1])))
                    for r in conn.execute(f'PRAGMA table_info("{table}")')]
            count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            return TableInfo(table=table, row_count=count, columns=cols)
        finally:
            conn.close()

    @mcp.tool(annotations=READ_ONLY)
    def get_sample_rows(table: str, n: Annotated[int, Field(ge=1, le=20)] = 5) -> QueryResult:
        """First n rows of a table, to see what the values look like."""
        conn = _connect(guarded=False)
        try:
            _check_table(conn, table)
        finally:
            conn.close()
        start = time.perf_counter()
        cols, rows, _ = _run(f'SELECT * FROM "{table}" LIMIT {n}', n)
        return QueryResult(columns=cols, rows=rows, row_count=len(rows), truncated=False,
                           elapsed_ms=round((time.perf_counter() - start) * 1000, 1))

    @mcp.tool(annotations=READ_ONLY)
    def run_sql_query(sql: Annotated[str, Field(min_length=6, max_length=5000)],
                      max_rows: Annotated[int, Field(ge=1, le=1000)] = 200) -> QueryResult:
        """Run ONE read-only SQLite SELECT (CTEs allowed) and return columns + rows.
        Revenue = quantity * unit_price * (1 - discount_pct / 100.0) (discount_pct is 0-100).
        Anything that writes or changes the schema is rejected. Results are capped at max_rows."""
        start = time.perf_counter()
        cols, rows, truncated = _run(sql, max_rows)
        return QueryResult(columns=cols, rows=rows, row_count=len(rows), truncated=truncated,
                           elapsed_ms=round((time.perf_counter() - start) * 1000, 1))

    @mcp.tool(annotations=READ_ONLY)
    def explain_query(sql: Annotated[str, Field(min_length=6, max_length=5000)]) -> list[str]:
        """Validate a SELECT without running it: returns SQLite's query plan, or the SQL error."""
        _, rows, _ = _run(f"EXPLAIN QUERY PLAN {sql}", 200)
        return [r[-1] for r in rows]

    @mcp.tool(annotations=READ_ONLY)
    def profile_column(table: str, column: str) -> ColumnProfile:
        """Quick stats for one column: nulls, distinct count, min/max/avg (numeric) and top 5 values."""
        conn = _connect(guarded=False)
        try:
            _check_table(conn, table)
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
            if column not in cols:
                raise ToolError(f"Unknown column '{column}' in {table}. Columns: {', '.join(cols)}")
            q = f'"{column}"'
            rows, nulls, distinct, mn, mx = conn.execute(
                f'SELECT COUNT(*), SUM({q} IS NULL), COUNT(DISTINCT {q}), MIN({q}), MAX({q}) FROM "{table}"').fetchone()
            numeric = conn.execute(
                f'SELECT COUNT(*) = SUM(typeof({q}) IN (\'integer\',\'real\')) FROM "{table}" WHERE {q} IS NOT NULL'
            ).fetchone()[0]
            avg = conn.execute(f'SELECT AVG({q}) FROM "{table}"').fetchone()[0] if numeric else None
            top = [TopValue(value=v, count=c) for v, c in conn.execute(
                f'SELECT {q}, COUNT(*) c FROM "{table}" GROUP BY {q} ORDER BY c DESC LIMIT 5')]
            return ColumnProfile(table=table, column=column, rows=rows, nulls=nulls or 0, distinct=distinct,
                                 min=mn, max=mx, avg=round(avg, 2) if avg is not None else None, top_values=top)
        finally:
            conn.close()

    @mcp.resource("schema://database", mime_type="text/plain")
    def database_schema() -> str:
        """CREATE statements for every table (the full schema in one read)."""
        conn = _connect(guarded=False)
        try:
            return "\n\n".join(r[0] + ";" for r in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))
        finally:
            conn.close()

    @mcp.prompt()
    def analyze_business_question(question: str) -> str:
        """Prompt template: answer a business question from the sales database."""
        return (f"Business question: {question}\n\n"
                "1. Call list_tables and describe_table for the relevant tables (never guess column names).\n"
                "2. Write one SELECT; validate it with explain_query.\n"
                "3. Run it with run_sql_query.\n"
                "4. Answer with the key insight, a small table of results, and the SQL you used. "
                "Revenue = quantity * unit_price * (1 - discount_pct/100); exclude cancelled orders unless asked.")

    return mcp


def main() -> None:
    from common.serve import serve

    serve(build_server(), SERVER)
