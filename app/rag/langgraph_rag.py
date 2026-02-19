from __future__ import annotations

from typing import NotRequired, TypedDict

from langgraph.graph import END, StateGraph

from app.rag.chunk_selector import ChunkSelector
from app.rag.index import RagIndex
from app.rag.llm_client import LLMClient
from app.rag.prompts import build_prompt, format_contexts


class RagState(TypedDict):
    question: str
    contexts: NotRequired[list[dict]]
    selected_contexts: NotRequired[list[dict]]
    answer: NotRequired[str]


def build_graph(
    index: RagIndex,
    client: LLMClient,
    chunk_selector: ChunkSelector | None = None,
) -> object:
    """Build the RAG LangGraph pipeline.

    Args:
        index: The RAG index used for retrieval.
        client: The LLM client used for generation.
        chunk_selector: Optional ChunkSelector instance. When provided, adds a
            selection step between retrieval and generation that filters out
            irrelevant chunks.

    Returns:
        Compiled LangGraph runnable.
    """
    graph = StateGraph(RagState)

    def retrieve(state: RagState) -> RagState:
        contexts = index.query(state["question"])
        return {"question": state["question"], "contexts": contexts}

    def generate(state: RagState) -> RagState:
        contexts = state.get("selected_contexts") or state.get("contexts", [])
        context_text = format_contexts(contexts)
        system, user_prompt = build_prompt(context_text, state["question"])
        answer = client.generate(user_prompt, system=system)
        return {
            "question": state["question"],
            "contexts": state.get("contexts", []),
            "answer": answer,
        }

    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)

    if chunk_selector is not None:

        def select_chunks(state: RagState) -> RagState:
            selected = chunk_selector.select(
                state.get("contexts", []), state["question"]
            )
            return {
                "question": state["question"],
                "contexts": state.get("contexts", []),
                "selected_contexts": selected,
            }

        graph.add_node("select_chunks", select_chunks)
        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "select_chunks")
        graph.add_edge("select_chunks", "generate")
    else:
        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "generate")

    graph.add_edge("generate", END)

    return graph.compile()
