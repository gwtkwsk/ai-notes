from __future__ import annotations

import logging
import re
import struct
from collections.abc import Callable

from app.data.repository import Repository
from app.rag.config import CHUNK_MAX_CHARS, FUSION_OVERSAMPLE_FACTOR, TOP_K
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.llm_client import LLMClient
from app.rag.query_expander import QueryExpander

logger = logging.getLogger(__name__)

_HEADING_SPLIT_RE = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)


class RagIndex:
    def __init__(
        self,
        repo: Repository,
        client: LLMClient,
        query_expander: QueryExpander | None = None,
    ) -> None:
        self._repo = repo
        self._client = client
        self._query_expander = query_expander or QueryExpander(client)

    # -- vector serialisation ------------------------------------------------

    @staticmethod
    def _serialize_vector(vec: list[float]) -> bytes:
        """Encode a float list as a little-endian float32 BLOB."""
        return struct.pack(f"<{len(vec)}f", *vec)

    # -- markdown chunking ---------------------------------------------------

    @staticmethod
    def _chunk_text(text: str, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
        """Split markdown text into chunks at heading boundaries.

        Short texts (<= *max_chars*) are returned as a single chunk.
        Longer texts are split at ``#``-headings; tiny adjacent sections
        are merged so that every chunk has a reasonable size.

        A dedicated chunking library such as *chonkie*
        (``RecursiveChunker(recipe='markdown')``) could replace this helper
        if more sophisticated, token-aware splitting is ever needed.
        """
        text = text.strip()
        if not text:
            return []
        if len(text) <= max_chars:
            return [text]

        # Split at markdown headings
        sections = _HEADING_SPLIT_RE.split(text)
        sections = [s.strip() for s in sections if s.strip()]

        if len(sections) <= 1:
            # No headings — fall back to paragraph boundaries
            paragraphs = text.split("\n\n")
            sections = [p.strip() for p in paragraphs if p.strip()]

        if not sections:
            return [text]

        # Merge small adjacent sections
        chunks: list[str] = []
        current = sections[0]
        for section in sections[1:]:
            if len(current) + len(section) + 2 <= max_chars:
                current = current + "\n\n" + section
            else:
                chunks.append(current)
                current = section
        if current:
            chunks.append(current)

        return chunks if chunks else [text]

    # -- index building ------------------------------------------------------

    def index_note(self, note_id: int) -> bool:
        """Index or re-index a single note.

        Args:
            note_id: The ID of the note to index.

        Returns:
            True if indexing succeeded, False otherwise.
        """
        note = self._repo.get_note(note_id)
        if note is None:
            logger.warning(f"Note {note_id} not found, skipping indexing")
            return False

        text = self._note_text(note)
        note_title = note.get("title", "")[:50]
        chunks = self._chunk_text(text)
        logger.debug(
            f"Indexing note id={note_id}, title='{note_title}', chunks={len(chunks)}"
        )

        chunk_embeddings: list[tuple[str, bytes]] = []
        for chunk in chunks:
            vector = self._client.embed(chunk)
            if not vector:
                logger.warning(f"Failed to embed chunk of note {note_id}, skipping")
                continue
            blob = self._serialize_vector(vector)
            chunk_embeddings.append((chunk, blob))

        if chunk_embeddings:
            self._repo.replace_note_embeddings(note_id, chunk_embeddings)
            logger.info(
                f"Successfully indexed note {note_id} with "
                f"{len(chunk_embeddings)} chunks"
            )
            return True
        else:
            logger.warning(f"No embeddings generated for note {note_id}")
            return False

    def build_index(
        self,
        progress_cb: Callable[[int, int, dict], None] | None = None,
    ) -> int:
        notes = self._repo.list_notes_for_embedding()
        total = len(notes)
        logger.info(f"Starting index build for {total} notes")
        self._repo.clear_embeddings()
        indexed_count = 0
        for idx, note in enumerate(notes, start=1):
            text = self._note_text(note)
            note_title = note.get("title", "")[:50]
            chunks = self._chunk_text(text)
            logger.debug(
                f"Embedding note {idx}/{total}: id={note['id']}, "
                f"title='{note_title}', chunks={len(chunks)}"
            )
            chunk_embeddings: list[tuple[str, bytes]] = []
            for chunk in chunks:
                vector = self._client.embed(chunk)
                if not vector:
                    logger.warning(
                        f"Failed to embed chunk of note {note['id']}, skipping"
                    )
                    continue
                blob = self._serialize_vector(vector)
                chunk_embeddings.append((chunk, blob))
            if chunk_embeddings:
                self._repo.replace_note_embeddings(note["id"], chunk_embeddings)
                indexed_count += 1
            if progress_cb is not None:
                progress_cb(idx, total, note)
        logger.info(f"Index build complete: {indexed_count}/{total} notes indexed")
        return total

    # -- querying ------------------------------------------------------------

    def query(
        self,
        question: str,
        top_k: int = TOP_K,
        transformed_query_count: int = 1,
        hybrid: bool | None = None,
        use_hybrid: bool | None = None,
        status_cb: Callable[[str], None] | None = None,
    ) -> list[dict]:
        effective_hybrid = self._resolve_hybrid(hybrid, use_hybrid)

        logger.info(
            "RAG query: '%s' (top_k=%d, transformed_query_count=%d, hybrid=%s)",
            question,
            top_k,
            transformed_query_count,
            effective_hybrid,
        )
        # Fetch more candidates per leg before fusion for better recall.
        fetch_k = top_k * FUSION_OVERSAMPLE_FACTOR

        if status_cb is not None:
            status_cb("Expanding the question")

        expanded_questions = self._expand_questions(question, transformed_query_count)
        if not expanded_questions:
            logger.warning("Query expansion produced no queries; aborting retrieval")
            return []

        logger.info(
            "Retrieval plan: %d query leg(s), fetch_k=%d, hybrid=%s",
            len(expanded_questions),
            fetch_k,
            effective_hybrid,
        )

        if status_cb is not None:
            status_cb("Searching notes")

        ranked_lists, chunk_query_blob = self._collect_ranked_lists(
            expanded_questions,
            fetch_k,
            effective_hybrid,
        )

        if not ranked_lists:
            logger.warning("No retrieval legs succeeded for question")
            return []

        logger.info(
            "Fusing %d ranked list(s) via RRF",
            len(ranked_lists),
        )
        if len(ranked_lists) == 1:
            fused = ranked_lists[0]
        else:
            fused = reciprocal_rank_fusion(ranked_lists)

        results = fused[:top_k]

        # BM25 results carry the full note content; replace each result's
        # content with the nearest chunk text so the LLM receives a focused
        # chunk rather than a whole note.  Vector-search results already
        # have chunk text, but the lookup is cheap and keeps the logic uniform.
        self._hydrate_chunk_content(results, chunk_query_blob)

        logger.info(
            "RRF merged to %d unique docs; returning top %d",
            len(fused),
            len(results),
        )
        for i, res in enumerate(results):
            score = res.get("rrf_score")
            score_str = f"{score:.4f}" if isinstance(score, float) else "N/A"
            logger.debug(
                "  [%d] id=%-4s  rrf=%-8s  title='%s'",
                i + 1,
                res.get("id"),
                score_str,
                res.get("title", "")[:60],
            )
        return results

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _resolve_hybrid(
        hybrid: bool | None,
        use_hybrid: bool | None,
    ) -> bool:
        effective_hybrid = hybrid if hybrid is not None else True
        if use_hybrid is not None:
            return use_hybrid
        return effective_hybrid

    def _expand_questions(
        self,
        question: str,
        transformed_query_count: int,
    ) -> list[str]:
        stripped_question = question.strip()
        fallback = [stripped_question] if stripped_question else []
        try:
            expanded_questions = self._query_expander.expand(
                question,
                transformed_query_count,
            )
        except Exception:
            logger.exception(
                "Query expansion failed, falling back to original question"
            )
            return fallback

        if not expanded_questions:
            logger.debug("Expander returned empty list; using original question as-is")
            return fallback

        if len(expanded_questions) == 1 and expanded_questions[0] == stripped_question:
            logger.debug("Query expansion skipped (count=1); using original question")
        else:
            logger.info(
                "Query expanded to %d variant(s): %s",
                len(expanded_questions),
                " | ".join(f"'{q}'" for q in expanded_questions),
            )
        return expanded_questions

    def _collect_ranked_lists(
        self,
        expanded_questions: list[str],
        fetch_k: int,
        effective_hybrid: bool,
    ) -> tuple[list[list[dict]], bytes | None]:
        ranked_lists: list[list[dict]] = []
        chunk_query_blob: bytes | None = None

        for leg_idx, expanded_question in enumerate(expanded_questions, start=1):
            logger.debug(
                "Leg %d/%d: embedding '%s'",
                leg_idx,
                len(expanded_questions),
                expanded_question,
            )
            q_vec = self._client.embed(expanded_question)
            if not q_vec:
                logger.warning(
                    "Leg %d/%d: embedding failed, skipping leg — query='%s'",
                    leg_idx,
                    len(expanded_questions),
                    expanded_question,
                )
                continue

            logger.debug(
                "Leg %d/%d: embedding dimension=%d",
                leg_idx,
                len(expanded_questions),
                len(q_vec),
            )
            query_blob = self._serialize_vector(q_vec)
            if chunk_query_blob is None:
                chunk_query_blob = query_blob

            vector_results = self._repo.search_notes_by_embedding(query_blob, fetch_k)
            logger.debug(
                "Leg %d/%d: vector search returned %d result(s)",
                leg_idx,
                len(expanded_questions),
                len(vector_results),
            )
            ranked_lists.append(vector_results)

            if effective_hybrid:
                bm25_results = self._repo.search_notes_by_bm25(
                    expanded_question,
                    fetch_k,
                )
                logger.debug(
                    "Leg %d/%d: BM25 search returned %d result(s)",
                    leg_idx,
                    len(expanded_questions),
                    len(bm25_results),
                )
                ranked_lists.append(bm25_results)

        return ranked_lists, chunk_query_blob

    def _hydrate_chunk_content(
        self,
        results: list[dict],
        chunk_query_blob: bytes | None,
    ) -> None:
        if chunk_query_blob is None:
            return
        for result in results:
            note_id = result.get("id")
            if note_id is None:
                continue
            chunk_text = self._repo.get_best_chunk_text(note_id, chunk_query_blob)
            if chunk_text is not None:
                result["content"] = chunk_text

    def _note_text(self, note: dict) -> str:
        title = note.get("title", "")
        content = note.get("content", "")
        return f"{title}\n\n{content}".strip()
