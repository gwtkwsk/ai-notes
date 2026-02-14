
from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from app.data.repository import Repository
from app.rag.index import RagIndex
from app.rag.ollama_client import OllamaClient
from app.rag.prompts import build_prompt, format_contexts

if TYPE_CHECKING:
    from app.config import Config

logger = logging.getLogger(__name__)


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

        self._graph: Any | None = None

    def build_index(
        self,
        progress_cb: Callable[[int, int, dict], None] | None = None,
    ) -> int:
        return self._index.build_index(progress_cb)

    def ask(self, question: str) -> dict[str, list[str] | str]:
        if self._graph is None:
            try:
                from app.rag.langgraph_rag import build_graph
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Brakuje zależności 'langgraph' wymaganej dla trybu ask(). "
                    "Użyj streamingu albo doinstaluj zależności projektu."
                ) from exc
            self._graph = build_graph(self._index, self._client)

        assert self._graph is not None
        state = self._graph.invoke({"question": question})
        sources = [note.get("title", "Untitled") for note in state.get("contexts", [])]
        answer = state.get("answer", "")
        return {
            "answer": answer,
            "thinking": "",
            "sources": sources[: self._config.top_k],
        }

    def ask_stream(
        self,
        question: str,
        cancel_cb: Callable[[], bool] | None = None,
        status_cb: Callable[[str], None] | None = None,
    ) -> Iterator[dict]:
        logger.info(f"RAG query started: {question}")
        contexts = self._index.query(question, status_cb=status_cb)
        logger.info(f"Retrieved {len(contexts)} context documents")
        system, user_prompt = build_prompt(format_contexts(contexts), question)
        logger.debug(f"System message: {system}")
        logger.debug(f"User prompt (first 300 chars): {user_prompt[:300]}...")

        for chunk in self._client.generate_stream(user_prompt, system=system):
            if cancel_cb is not None and cancel_cb():
                logger.info("RAG query cancelled by user")
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

        logger.info("RAG query completed successfully")
        yield {
            "answer_delta": "",
            "thinking_delta": "",
            "done": True,
        }

    def clone_for_thread(self) -> RagService:
        repo = Repository(self._db_path)
        return RagService(repo, self._config)

    def close(self) -> None:
        self._repo.close()
