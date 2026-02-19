from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from app.data.repository import Repository
from app.rag.chunk_selector import ChunkSelector
from app.rag.client_factory import create_llm_client
from app.rag.config import CHUNK_SELECTION_ENABLED
from app.rag.index import RagIndex
from app.rag.llm_client import LLMClient
from app.rag.prompts import build_prompt, format_contexts

if TYPE_CHECKING:
    from app.config import Config

logger = logging.getLogger(__name__)


class RagService:
    def __init__(self, repo: Repository, config: Config) -> None:
        self._repo = repo
        self._db_path = repo.db_path
        self._config = config
        self._client: LLMClient = create_llm_client(config)
        self._index = RagIndex(repo, self._client)
        self._chunk_selector: ChunkSelector | None = (
            ChunkSelector(self._client) if CHUNK_SELECTION_ENABLED else None
        )

        self._graph: Any | None = None

    def build_index(
        self,
        progress_cb: Callable[[int, int, dict], None] | None = None,
    ) -> int:
        return self._index.build_index(progress_cb)

    def index_note(self, note_id: int) -> bool:
        """Index or re-index a single note.

        Args:
            note_id: The ID of the note to index.

        Returns:
            True if indexing succeeded, False otherwise.
        """
        return self._index.index_note(note_id)

    def ask(self, question: str) -> dict[str, list[str] | str]:
        if self._graph is None:
            try:
                from app.rag.langgraph_rag import build_graph
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Brakuje zależności 'langgraph' wymaganej dla trybu ask(). "
                    "Użyj streamingu albo doinstaluj zależności projektu."
                ) from exc
            self._graph = build_graph(
                self._index, self._client, chunk_selector=self._chunk_selector
            )

        assert self._graph is not None
        state = self._graph.invoke({"question": question})
        sources = [
            note.get("title", "Untitled")
            for note in (state.get("selected_contexts") or state.get("contexts", []))
        ]
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
        logger.info(f"RAG query started: '{question}'")
        contexts = self._index.query(question, status_cb=status_cb)
        logger.info(f"Retrieved {len(contexts)} context documents")

        if self._chunk_selector is not None:
            if status_cb is not None:
                status_cb("Evaluating chunk relevance…")
            contexts = self._chunk_selector.select(contexts, question)
            logger.info(f"After chunk selection: {len(contexts)} relevant chunks")

        system, user_prompt = build_prompt(format_contexts(contexts), question)
        logger.debug(f"System message: {system}")
        logger.debug(f"User prompt (first 300 chars): {user_prompt[:300]}...")

        sources = [
            {"id": int(c["id"]), "title": c.get("title", "Untitled")} for c in contexts
        ]
        if status_cb is not None:
            status_cb("Generating answer…")
        for chunk in self._client.generate_stream(user_prompt, system=system):
            if cancel_cb is not None and cancel_cb():
                logger.info("RAG query cancelled by user")
                yield {
                    "answer_delta": "",
                    "thinking_delta": "",
                    "done": True,
                    "cancelled": True,
                    "sources": sources,
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
            "sources": sources,
        }

    def clone_for_thread(self) -> RagService:
        repo = Repository(self._db_path)
        return RagService(repo, self._config)

    def close(self) -> None:
        self._repo.close()
