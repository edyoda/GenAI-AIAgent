import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# port 8000 is used by weather_server, so the HTTP transports use 8001
mcp = FastMCP("SQLiteDB", port=8001)

# Change this path to point to your actual SQLite database file
DB_PATH = Path(__file__).resolve().parent / "sql_db.db"


class SqliteDatabase:
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).expanduser())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        self.insights: list[str] = []

    def _init_database(self):
        """Initialize connection to the SQLite database"""
        # print("Initializing database connection")
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.close()

    def _synthesize_memo(self) -> str:
        """Synthesizes business insights into a formatted memo"""
        # print(f"Synthesizing memo with {len(self.insights)} insights")
        if not self.insights:
            return "No business insights have been discovered yet."

        insights = "\n".join(f"- {insight}" for insight in self.insights)

        memo = "📊 Business Intelligence Memo 📊\n\n"
        memo += "Key Insights Discovered:\n\n"
        memo += insights

        if len(self.insights) > 1:
            memo += "\nSummary:\n"
            memo += f"Analysis has revealed {len(self.insights)} key business insights that suggest opportunities for strategic optimization and growth."

        # print("Generated basic memo format")
        return memo

    def _get_schema(self, table_name: str) -> str:
        try:
            with open("schema.json", "r") as f:
                data = json.load(f)
                return data[table_name]
        except FileNotFoundError:
            raise FileNotFoundError("schema.json file not found")
        except KeyError:
            raise KeyError(f"Table '{table_name}' not found in schema.json")

    def _execute_query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a SQL query and return results as a list of dictionaries"""
        # print(f"Executing query: {query}")
        try:
            # stdout carries the MCP protocol under stdio, so log to stderr
            print(query, file=sys.stderr)
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                with closing(conn.cursor()) as cursor:
                    if params:
                        cursor.execute(query, params)
                    else:
                        cursor.execute(query)

                    # if not query.strip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER')):
                    #     conn.commit()
                    #     affected = cursor.rowcount
                    #     # print(f"Write query affected {affected} rows")
                    #     return [{"affected_rows": affected}]

                    results = [dict(row) for row in cursor.fetchall()]
                    # print(f"Read query returned {len(results)} rows")
                    return results
        except Exception as e:
            # print(f"Database error executing query: {e}")
            raise


db = SqliteDatabase(DB_PATH)


@mcp.tool()
def read_query(query: str) -> str:
    """Execute a SELECT query on the SQLite database"""
    # FIXME : update here
    if not query.strip().upper().startswith("SELECT"):
        return "Error: Only SELECT queries are allowed for read_query"
    try:
        return str(db._execute_query(query))
    except sqlite3.Error as e:
        return f"Database error: {e}"


@mcp.tool()
def list_tables() -> str:
    """List all tables in the SQLite database"""
    try:
        return str(
            db._execute_query("SELECT name FROM sqlite_master WHERE type='table'")
        )
    except sqlite3.Error as e:
        return f"Database error: {e}"


@mcp.tool()
def describe_table(table_name: str) -> str:
    """Get the schema information for a specific table"""
    # results = db._get_schema(table_name)
    try:
        return str(db._execute_query(f"PRAGMA table_info({table_name})"))
    except sqlite3.Error as e:
        return f"Database error: {e}"


@mcp.tool()
def append_insight(insight: str) -> str:
    """Add a business insight to the memo"""
    db.insights.append(insight)
    memo = db._synthesize_memo()
    print(f"Memo: {memo}")
    return "Insight added to memo"


# @mcp.tool()
# def create_table(query: str) -> str:
#     """Create a new table in the SQLite database"""
#     if not query.strip().upper().startswith("CREATE TABLE"):
#         return "Error: Only CREATE TABLE statements are allowed"
#     db._execute_query(query)
#     return "Table created successfully"


TRANSPORT_URLS = {
    "sse": f"http://{mcp.settings.host}:{mcp.settings.port}{mcp.settings.sse_path}",
    "streamable-http": f"http://{mcp.settings.host}:{mcp.settings.port}{mcp.settings.streamable_http_path}",
}

if __name__ == "__main__":
    # usage: python sqlite_server.py [sse | streamable-http | stdio]   (default: sse)
    transport = sys.argv[1] if len(sys.argv) > 1 else "sse"
    if transport not in ("sse", "streamable-http", "stdio"):
        sys.exit(f"Unknown transport '{transport}'. Use: sse, streamable-http or stdio")

    # log to stderr: under stdio, stdout carries the MCP protocol
    print(f"SQLite MCP server | database: {DB_PATH}", file=sys.stderr)
    if transport == "stdio":
        print(
            "Running on stdio - waiting for an MCP client to connect (Ctrl+C to stop)",
            file=sys.stderr,
        )
    else:
        print(
            f"Running {transport} at {TRANSPORT_URLS[transport]} (Ctrl+C to stop)",
            file=sys.stderr,
        )

    mcp.run(transport=transport)


