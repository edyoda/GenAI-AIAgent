"""Document processing (ingestion) pipeline.

LangGraph graph: load_document -> split_document -> store_chunks -> END
"""

import os

from langchain_community.document_loaders import (
    Docx2txtLoader,
    PyPDFLoader,
    TextLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from model_inference import vector_store

LOADERS_BY_EXTENSION = {
    ".txt": TextLoader,
    ".md": TextLoader,
    ".pdf": PyPDFLoader,
    ".docx": Docx2txtLoader,
}


class DocumentProcessingState(TypedDict, total=False):
    file_path: str
    documents: list
    chunks: list
    num_chunks: int
    status: str
    error: str


def load_document(state: DocumentProcessingState) -> dict:
    """Loads a document from disk into LangChain `Document` objects."""
    file_path = state["file_path"]
    extension = os.path.splitext(file_path)[1].lower()
    loader_cls = LOADERS_BY_EXTENSION.get(extension)

    if not os.path.exists(file_path):
        return {"status": "failed", "error": f"File not found: {file_path}"}

    if loader_cls is None:
        return {
            "status": "failed",
            "error": f"Unsupported file type '{extension}'. Supported: "
            f"{list(LOADERS_BY_EXTENSION)}",
        }

    documents = loader_cls(file_path).load()
    return {"documents": documents, "status": "loaded"}


def split_document(state: DocumentProcessingState) -> dict:
    """Splits loaded documents into overlapping chunks for embedding."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    chunks = splitter.split_documents(state["documents"])
    return {"chunks": chunks, "status": "split"}


def store_chunks(state: DocumentProcessingState) -> dict:
    """Embeds chunks and persists them in the shared vector store."""
    chunks = state["chunks"]
    vector_store.add_documents(chunks)
    return {"num_chunks": len(chunks), "status": "stored"}


def route_after_load(state: DocumentProcessingState) -> str:
    return "failed" if state["status"] == "failed" else "loaded"


def build_document_pipeline():
    workflow = StateGraph(DocumentProcessingState)

    workflow.add_node("load_document", load_document)
    workflow.add_node("split_document", split_document)
    workflow.add_node("store_chunks", store_chunks)

    workflow.set_entry_point("load_document")

    workflow.add_conditional_edges(
        "load_document",
        route_after_load,
        {"failed": END, "loaded": "split_document"},
    )
    workflow.add_edge("split_document", "store_chunks")
    workflow.add_edge("store_chunks", END)

    return workflow.compile()


document_pipeline = build_document_pipeline()


def run_document_pipeline(file_path: str) -> DocumentProcessingState:
    return document_pipeline.invoke({"file_path": file_path})


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python process_document.py <file_path>")
        sys.exit(1)

    result = run_document_pipeline(sys.argv[1])

    if result.get("status") == "failed":
        print(f"Ingestion failed: {result.get('error')}")
    else:
        print(f"Ingested {result.get('num_chunks')} chunks from {sys.argv[1]}")
