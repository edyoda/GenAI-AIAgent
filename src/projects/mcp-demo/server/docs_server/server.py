"""Document retrieval MCP server (port 8002).

Scopes: `docs:read` to connect and search; `docs:write` additionally for `ingest_documents`
(per-tool authorization; the demo agent doesn't have it, the docs-admin client does).
The server only retrieves. Writing the answer is the client's LLM's job.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from common.auth import auth_config, require_scope
from common.config import RESOURCE_SERVERS
from common.logs import request_logger, setup_logging
from docs_server import store

SERVER = RESOURCE_SERVERS["docs"]
log = setup_logging("docs")

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
MIN_SCORE = 0.30  # below this cosine similarity a chunk is treated as irrelevant

Query = Annotated[str, Field(min_length=3, max_length=500, description="Natural-language search query")]


class Chunk(BaseModel):
    chunk_id: str
    source: str
    section: str
    score: float = Field(description="Cosine similarity, 0-1 (higher is more relevant)")
    text: str


class SearchResult(BaseModel):
    query: str
    results: list[Chunk]


class Citation(BaseModel):
    ref: int
    source: str
    section: str
    chunk_id: str
    score: float


class Context(BaseModel):
    query: str
    found: bool
    context: str = Field(description="Relevant passages, each prefixed with its [ref] number")
    citations: list[Citation]


class ChunkWithNeighbours(BaseModel):
    chunk_id: str
    source: str
    section: str
    text: str = Field(description="The chunk plus its neighbours, in document order")


def _require_index() -> None:
    if not store.catalog():
        raise ToolError("No documents are indexed yet. Ask an admin to run ingest.")


def build_server(auth: bool = True) -> MCPServer:
    mcp = MCPServer(
        "docs",
        instructions="Semantic search over company documents (handbook, travel & expense policy, "
                     "security policy, product FAQ). Use get_context to ground answers with citations.",
        middleware=[request_logger(log)],
        **(auth_config(SERVER) if auth else {}),
    )

    @mcp.tool(annotations=READ_ONLY)
    def list_documents() -> dict[str, int]:
        """Indexed documents and how many chunks each has."""
        return store.catalog()

    @mcp.tool(annotations=READ_ONLY)
    def search_documents(query: Query, k: Annotated[int, Field(ge=1, le=10)] = 5,
                         source: str | None = None) -> SearchResult:
        """Semantic search. Returns the top-k chunks with relevance score, source and section.
        Optionally restrict to one document with `source` (a name from list_documents)."""
        _require_index()
        if source and source not in store.catalog():
            raise ToolError(f"Unknown source '{source}'. Use list_documents to see valid names.")
        return SearchResult(query=query, results=[Chunk(**r) for r in store.search(query, k, source)])

    @mcp.tool(annotations=READ_ONLY)
    def get_context(query: Query, k: Annotated[int, Field(ge=1, le=8)] = 4,
                    max_chars: Annotated[int, Field(ge=500, le=12000)] = 4000) -> Context:
        """Best tool for answering a question: returns relevant passages merged into one context
        block with [n] reference markers, plus the citation list. `found=false` means nothing
        relevant was found, so don't answer from the documents."""
        _require_index()
        hits = [h for h in store.search(query, k) if h["score"] >= MIN_SCORE]
        parts, citations, used = [], [], 0
        for h in hits:
            block = f"[{len(citations) + 1}] ({h['source']} › {h['section']})\n{h['text']}"
            if used + len(block) > max_chars and citations:
                break
            parts.append(block)
            used += len(block)
            citations.append(Citation(ref=len(citations) + 1, source=h["source"], section=h["section"],
                                      chunk_id=h["chunk_id"], score=h["score"]))
        return Context(query=query, found=bool(citations), context="\n\n".join(parts), citations=citations)

    @mcp.tool(annotations=READ_ONLY)
    def get_chunk(chunk_id: str, neighbours: Annotated[int, Field(ge=0, le=2)] = 1) -> ChunkWithNeighbours:
        """Full text of a chunk (id like 'product-faq.md::3') plus `neighbours` chunks on each side,
        for when a search hit is cut off mid-thought."""
        source, _, idx = chunk_id.rpartition("::")
        if not source or not idx.isdigit():
            raise ToolError("chunk_id must look like '<source>::<n>', e.g. 'product-faq.md::3'.")
        i = int(idx)
        ids = [f"{source}::{j}" for j in range(max(0, i - neighbours), i + neighbours + 1)]
        found = store.get_chunks(ids)
        if chunk_id not in found:
            raise ToolError(f"Chunk '{chunk_id}' not found.")
        return ChunkWithNeighbours(chunk_id=chunk_id, source=source, section=found[chunk_id]["section"],
                                   text="\n\n".join(found[c]["text"] for c in ids if c in found))

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True))
    def ingest_documents() -> dict[str, int]:
        """Admin only (scope docs:write): rebuild the index from the server's documents folder."""
        if auth:
            require_scope("docs:write")
        return store.ingest()

    @mcp.resource("docs://catalog", mime_type="application/json")
    def document_catalog() -> dict[str, int]:
        """Indexed documents with chunk counts."""
        return store.catalog()

    return mcp


def main() -> None:
    from common.serve import serve

    if not store.catalog():
        log.warning("index is empty. Run `python src/projects/mcp-demo/server/main.py ingest` first")
    serve(build_server(), SERVER)
