"""Chroma vector store for the docs server: ingestion + search.

Embeddings use Chroma's built-in local model (all-MiniLM-L6-v2, ONNX), so no API key is needed.
The model is downloaded once (~80 MB) to ~/.cache/chroma on the first ingest.
"""

from __future__ import annotations

from pathlib import Path

import chromadb
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from common.config import CHROMA_DIR, DOCS_DIR

COLLECTION = "documents"
SUPPORTED = {".md", ".txt"}

_header_splitter = MarkdownHeaderTextSplitter([("#", "h1"), ("##", "h2"), ("###", "h3")], strip_headers=False)
_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)


def _client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


def collection() -> chromadb.Collection:
    return _client().get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})


def chunk_file(path: Path) -> list[tuple[str, str, dict]]:
    """(id, text, metadata) per chunk. Split on markdown headings first, then by size."""
    text = path.read_text(encoding="utf-8")
    sections = _header_splitter.split_text(text) if path.suffix == ".md" else []
    pieces = _splitter.split_documents(sections) if sections else _splitter.create_documents([text])
    chunks = []
    for i, doc in enumerate(pieces):
        section = " › ".join(doc.metadata[h] for h in ("h1", "h2", "h3") if h in doc.metadata)
        chunks.append((f"{path.name}::{i}", doc.page_content,
                       {"source": path.name, "chunk_index": i, "section": section or path.stem}))
    return chunks


def ingest(docs_dir: Path = DOCS_DIR) -> dict[str, int]:
    """Rebuild the collection from scratch. Returns chunks per source."""
    client = _client()
    if COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)
    col = collection()
    counts: dict[str, int] = {}
    for path in sorted(p for p in docs_dir.iterdir() if p.suffix.lower() in SUPPORTED):
        chunks = chunk_file(path)
        if chunks:
            ids, texts, metas = zip(*chunks)
            col.add(ids=list(ids), documents=list(texts), metadatas=list(metas))
        counts[path.name] = len(chunks)
    return counts


def catalog() -> dict[str, int]:
    """Chunks per source currently in the index."""
    counts: dict[str, int] = {}
    for meta in collection().get(include=["metadatas"])["metadatas"] or []:
        counts[meta["source"]] = counts.get(meta["source"], 0) + 1
    return dict(sorted(counts.items()))


def search(query: str, k: int, source: str | None = None) -> list[dict]:
    col = collection()
    if col.count() == 0:
        return []
    res = col.query(query_texts=[query], n_results=min(k, col.count()),
                    where={"source": source} if source else None,
                    include=["documents", "metadatas", "distances"])
    return [
        {"chunk_id": cid, "source": meta["source"], "section": meta["section"],
         "score": round(1 - dist, 4), "text": text}
        for cid, text, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0])
    ]


def get_chunks(ids: list[str]) -> dict[str, dict]:
    res = collection().get(ids=ids, include=["documents", "metadatas"])
    return {cid: {"text": t, **m} for cid, t, m in zip(res["ids"], res["documents"], res["metadatas"])}
