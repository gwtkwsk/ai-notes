from __future__ import annotations

from typing import NotRequired, TypedDict

from langgraph.graph import END, StateGraph

from app.rag.index import RagIndex
from app.rag.ollama_client import OllamaClient
from app.rag.prompts import build_prompt, format_contexts


class RagState(TypedDict):
    question: str
    contexts: NotRequired[list[dict]]
    answer: NotRequired[str]


def build_graph(index: RagIndex, client: OllamaClient) -> object:
    graph = StateGraph(RagState)

    def retrieve(state: RagState) -> RagState:
        contexts = index.query(state["question"])
        return {"question": state["question"], "contexts": contexts, "answer": ""}

    def generate(state: RagState) -> RagState:
        contexts = state.get("contexts", [])
        context_text = format_contexts(contexts)
        system, user_prompt = build_prompt(context_text, state["question"])
        answer = client.generate(user_prompt, system=system)
        return {"question": state["question"], "contexts": contexts, "answer": answer}

    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)

    return graph.compile()
