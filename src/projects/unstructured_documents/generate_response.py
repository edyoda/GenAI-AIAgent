"""Retrieval and response generation pipeline.

LangGraph graph: validate_database -> (retrieve_context -> generate_response | END)
"""

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from model_inference import llm, vector_store
from typing_extensions import TypedDict

RAG_PROMPT = ChatPromptTemplate.from_template(
    "You are a helpful assistant answering questions using only the provided "
    "context. If the context does not contain the answer, say you don't know.\n\n"
    "Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"
)


class QueryState(TypedDict, total=False):
    question: str
    vectordb_status_flag: str
    context: list
    response: str


def validate_database(state: QueryState) -> dict:
    """Checks whether the vector store has any documents to retrieve from."""
    has_documents = len(vector_store.get()["ids"]) > 0
    return {"vectordb_status_flag": "ready" if has_documents else "empty"}


def route_after_validation(state: QueryState) -> str:
    return state["vectordb_status_flag"]


def retrieve_context(state: QueryState) -> dict:
    """Retrieves the most relevant chunks for the question."""
    context = vector_store.similarity_search(state["question"], k=4)
    return {"context": context}


def generate_response(state: QueryState) -> dict:
    """Generates an answer grounded in the retrieved context."""
    context_text = "\n\n".join(doc.page_content for doc in state["context"])
    prompt = RAG_PROMPT.invoke({"context": context_text, "question": state["question"]})
    result = llm.invoke(prompt)
    return {"response": result.content}


def respond_no_documents(state: QueryState) -> dict:
    return {
        "response": (
            "No documents have been ingested yet. Run the document processing "
            "pipeline (process_document.py) before asking questions."
        )
    }


def build_query_pipeline():
    workflow = StateGraph(QueryState)

    workflow.add_node("validate_database", validate_database)
    workflow.add_node("respond_no_documents", respond_no_documents)
    workflow.add_node("retrieve_context", retrieve_context)
    workflow.add_node("generate_response", generate_response)

    workflow.set_entry_point("validate_database")

    workflow.add_conditional_edges(
        "validate_database",
        route_after_validation,
        {"empty": "respond_no_documents", "ready": "retrieve_context"},
    )
    workflow.add_edge("respond_no_documents", END)
    workflow.add_edge("retrieve_context", "generate_response")
    workflow.add_edge("generate_response", END)

    return workflow.compile()


query_pipeline = build_query_pipeline()


def run_query_pipeline(question: str) -> QueryState:
    return query_pipeline.invoke({"question": question})


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python generate_response.py '<question>'")
        sys.exit(1)

    question = sys.argv[1]

    # question ="who is a generalist?"

    result = run_query_pipeline(question=question)
    print(result["response"])
