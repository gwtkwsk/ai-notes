from __future__ import annotations

import logging
import re
import struct
from collections.abc import Callable

from app.data.repository import Repository
from app.rag.config import CHUNK_MAX_CHARS, FUSION_OVERSAMPLE_FACTOR, TOP_K
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.llm_client import LLMClient

logger = logging.getLogger(__name__)

_HEADING_SPLIT_RE = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)


class RagIndex:
    def __init__(self, repo: Repository, client: LLMClient) -> None:
        self._repo = repo
        self._client = client

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
        status_cb: Callable[[str], None] | None = None,
    ) -> list[dict]:
        logger.info(f"RAG query: '{question}' (top_k={top_k})")
        # Fetch more candidates per leg before fusion for better recall.
        fetch_k = top_k * FUSION_OVERSAMPLE_FACTOR

        if status_cb is not None:
            status_cb("Embedding the question")
        q_vec = self._client.embed(question)
        if not q_vec:
            logger.warning("Failed to generate embedding for question")
            return []
        logger.info(f"Question embedded successfully (dimension={len(q_vec)})")

        if status_cb is not None:
            status_cb("Searching notes")
        query_blob = self._serialize_vector(q_vec)

        vector_results = self._repo.search_notes_by_embedding(query_blob, fetch_k)
        bm25_results = self._repo.search_notes_by_bm25(question, fetch_k)

        logger.info(
            f"Vector search: {len(vector_results)} results, "
            f"BM25 search: {len(bm25_results)} results"
        )

        fused = reciprocal_rank_fusion([vector_results, bm25_results])
        results = fused[:top_k]

        # BM25 results carry the full note content; replace each result's
        # content with the nearest chunk text so the LLM receives a focused
        # chunk rather than a whole note.  Vector-search results already
        # have chunk text, but the lookup is cheap and keeps the logic uniform.
        for result in results:
            note_id = result.get("id")
            if note_id is not None:
                chunk_text = self._repo.get_best_chunk_text(note_id, query_blob)
                if chunk_text is not None:
                    result["content"] = chunk_text

        logger.info(
            f"Hybrid search fused to {len(fused)} unique docs, returning {len(results)}"
        )
        if results:
            for i, res in enumerate(results[:3]):
                score = res.get("rrf_score")
                score_str = f"{score:.4f}" if isinstance(score, float) else "N/A"
                logger.debug(
                    f"  Result {i + 1}: id={res.get('id')}, "
                    f"title='{res.get('title', '')[:50]}', "
                    f"rrf_score={score_str}"
                )
        return results

    # -- helpers -------------------------------------------------------------

    def _note_text(self, note: dict) -> str:
        title = note.get("title", "")
        content = note.get("content", "")
        return f"{title}\n\n{content}".strip()
