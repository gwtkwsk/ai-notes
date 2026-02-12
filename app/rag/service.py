from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

from app.data.repository import Repository
from app.rag.index import RagIndex
from app.rag.ollama_client import OllamaClient

if TYPE_CHECKING:
    from app.config import Config


class RagService:
    def __init__(self, repo: Repository, config: Config) -> None:
        self._repo = repo
        self._db_path = repo.db_path
        self._config = config
        self._client = OllamaClient(
            config.ollama_base_url,
            config.embed_model,
            config.llm_model,
        )
        self._index = RagIndex(repo, self._client)
        self._graph = None

    def build_index(self, progress_cb=None) -> int:
        return self._index.build_index(progress_cb)

    def ask(self, question: str) -> Dict[str, List[str] | str]:
        if self._graph is None:
            try:
                from app.rag.langgraph_rag import build_graph
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Brakuje zależności 'langgraph' wymaganej dla trybu ask(). "
                    "Użyj streamingu albo doinstaluj zależności projektu."
                ) from exc
            self._graph = build_graph(self._index, self._client)

        state = self._graph.invoke({"question": question})
        sources = [note.get("title", "Untitled") for note in state.get("contexts", [])]
        answer, thinking = _split_thinking(state.get("answer", ""))
        return {"answer": answer, "thinking": thinking, "sources": sources[:self._config.top_k]}

    def ask_stream(self, question: str, cancel_cb=None, status_cb=None):
        contexts = self._index.query(question, status_cb=status_cb)
        prompt = _build_prompt(_format_contexts(contexts), question)
        
        for chunk in self._client.generate_stream(prompt):
            if cancel_cb is not None and cancel_cb():
                yield {
                    "answer_delta": "",
                    "thinking_delta": "",
                    "done": True,
                    "cancelled": True,
                }
                return
            yield {
                "answer_delta": chunk,
                "thinking_delta": "",
                "done": False,
            }
        
        yield {
            "answer_delta": "",
            "thinking_delta": "",
            "done": True,
        }

    def clone_for_thread(self) -> "RagService":
        repo = Repository(self._db_path)
        return RagService(repo, self._config)

    def close(self) -> None:
        self._repo.close()


def _split_thinking(text: str) -> tuple[str, str]:
    lower = text.lower()
    start = lower.find("<think>")
    end = lower.find("</think>")
    if start == -1 or end == -1 or end <= start:
        return text, ""
    thinking = text[start + len("<think>") : end].strip()
    answer = (text[:start] + text[end + len("</think>") :]).strip()
    return answer, thinking


def _build_prompt(contexts: str, question: str) -> str:
    return (
        "Jestes asystentem odpowiadajacym na pytania na podstawie notatek. "
        "Jesli odpowiedz nie wynika z notatek, powiedz wprost, ze nie masz informacji. "
        "Odpowiadaj zwięźle, po polsku.\n\n"
        f"Notatki:\n{contexts}\n\n"
        f"Pytanie: {question}\n\n"
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


def _split_thinking_stream(text: str) -> tuple[str, str, bool]:
    lower = text.lower()
    start = lower.find("<think>")
    if start == -1:
        return "", text, False
    end = lower.find("</think>", start + len("<think>"))
    if end == -1:
        thinking = text[start + len("<think>") :]
        answer = text[:start]
        return thinking.strip(), answer.strip(), True
    thinking = text[start + len("<think>") : end]
    answer = (text[:start] + text[end + len("</think>") :]).strip()
    return thinking.strip(), answer.strip(), False


def _extract_deltas(text: str, in_think: bool, flush: bool = False) -> tuple[str, str, bool, str]:
    thinking_delta = ""
    answer_delta = ""
    lower = text.lower()
    tail_keep = max(len("<think>"), len("</think>")) - 1
    
    while text:
        if not in_think:
            idx = lower.find("<think>")
            if idx == -1:
                # No tag found
                if flush:
                    # Flush mode: send everything
                    answer_delta += text
                    text = ""
                else:
                    # Keep last tail_keep chars as buffer
                    if len(text) > tail_keep:
                        answer_delta += text[:-tail_keep]
                        text = text[-tail_keep:]
                break
            answer_delta += text[:idx]
            text = text[idx + len("<think>") :]
            lower = text.lower()
            in_think = True
        else:
            idx = lower.find("</think>")
            if idx == -1:
                # No closing tag found
                if flush:
                    # Flush mode: send everything
                    thinking_delta += text
                    text = ""
                else:
                    # Keep last tail_keep chars as buffer
                    if len(text) > tail_keep:
                        thinking_delta += text[:-tail_keep]
                        text = text[-tail_keep:]
                break
            thinking_delta += text[:idx]
            text = text[idx + len("</think>") :]
            lower = text.lower()
            in_think = False

    return thinking_delta, answer_delta, in_think, text
