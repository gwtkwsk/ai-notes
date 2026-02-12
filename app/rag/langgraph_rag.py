from __future__ import annotations

from typing import Dict, List, TypedDict

from langgraph.graph import END, StateGraph

from app.rag.index import RagIndex
from app.rag.ollama_client import OllamaClient


class RagState(TypedDict):
    question: str
    contexts: List[Dict]
    answer: str


def build_graph(index: RagIndex, client: OllamaClient):
    graph = StateGraph(RagState)

    def retrieve(state: RagState) -> RagState:
        contexts = index.query(state["question"])
        return {"question": state["question"], "contexts": contexts, "answer": ""}

    def generate(state: RagState) -> RagState:
        contexts = state.get("contexts", [])
        context_text = _format_contexts(contexts)
        prompt = _build_prompt(context_text, state["question"])
        answer = client.generate(prompt)
        return {"question": state["question"], "contexts": contexts, "answer": answer}

    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)

    return graph.compile()


def _build_prompt(contexts: str, question: str) -> str:
    return (
        "Jestes asystentem odpowiadajacym na pytania na podstawie notatek. "
        "Jesli odpowiedz nie wynika z notatek, powiedz wprost, ze nie masz informacji. "
        "Odpowiadaj zwięźle, po polsku.\n\n"
        f"Notatki:\n{contexts}\n\n"
        f"Pytanie: {question}\n"
        "Odpowiedz:"
    )


def _format_contexts(contexts: List[Dict]) -> str:
    parts = []
    for idx, note in enumerate(contexts, start=1):
        title = note.get("title", "Untitled")
        content = note.get("content", "")
        content = content[:2000]
        parts.append(f"[{idx}] {title}\n{content}")
    return "\n\n".join(parts)
