from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from app.data.repository import Repository
from app.rag.chunk_selector import ChunkSelector
from app.rag.client_factory import create_llm_client
from app.rag.index import RagIndex
from app.rag.llm_client import LLMClient
from app.rag.prompts import build_prompt, format_contexts
from app.rag.query_expander import QueryExpander

if TYPE_CHECKING:
    from app.config import Config

logger = logging.getLogger(__name__)


class RagService:
    def __init__(self, repo: Repository, config: Config) -> None:
        self._repo = repo
        self._db_path = repo.db_path
        self._config = config
        self._client: LLMClient = create_llm_client(config)
        self._index = RagIndex(
            repo,
            self._client,
            query_expander=QueryExpander(self._client),
        )
        self._chunk_selector: ChunkSelector | None = (
            ChunkSelector(self._client) if config.chunk_selection_enabled else None
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
                self._index,
                self._client,
                chunk_selector=self._chunk_selector,
                top_k=self._config.top_k,
                transformed_query_count=self._config.rag_transformed_query_count,
                use_hybrid=self._config.hybrid_search_enabled,
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
        logger.info("RAG query started: '%s'", question)
        logger.debug(
            "RAG config — top_k=%d, transformed_query_count=%d, "
            "hybrid=%s, chunk_selection=%s",
            self._config.top_k,
            self._config.rag_transformed_query_count,
            self._config.hybrid_search_enabled,
            self._chunk_selector is not None,
        )
        contexts = self._index.query(
            question,
            top_k=self._config.top_k,
            transformed_query_count=self._config.rag_transformed_query_count,
            hybrid=self._config.hybrid_search_enabled,
            status_cb=status_cb,
        )
        logger.info("Retrieved %d context document(s)", len(contexts))
        for i, ctx in enumerate(contexts):
            score = ctx.get("rrf_score")
            score_str = f"{score:.4f}" if isinstance(score, float) else "N/A"
            logger.debug(
                "  Context [%d] id=%-4s  rrf=%-8s  title='%s'",
                i + 1,
                ctx.get("id"),
                score_str,
                ctx.get("title", "")[:60],
            )

        if self._chunk_selector is not None:
            if status_cb is not None:
                status_cb("Evaluating chunk relevance…")
            logger.info("Running chunk selection on %d candidate(s)", len(contexts))
            contexts = self._chunk_selector.select(contexts, question)
            logger.info("Chunk selection kept %d relevant chunk(s)", len(contexts))

        system, user_prompt = build_prompt(format_contexts(contexts), question)
        logger.debug("System prompt (%d chars): %s", len(system), system)
        logger.debug(
            "User prompt (%d chars, first 400): %s",
            len(user_prompt),
            user_prompt[:400],
        )

        sources = [
            {"id": int(c["id"]), "title": c.get("title", "Untitled")} for c in contexts
        ]
        logger.info(
            "Sources selected (%d): %s",
            len(sources),
            ", ".join(f"'{s['title']}'" for s in sources) or "(none)",
        )
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

        logger.info("RAG query completed successfully — answer streamed")
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
