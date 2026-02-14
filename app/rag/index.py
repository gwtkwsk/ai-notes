from __future__ import annotations

import logging
import re
import struct
from collections.abc import Callable

from app.data.repository import Repository
from app.rag.config import CHUNK_MAX_CHARS, TOP_K
from app.rag.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_HEADING_SPLIT_RE = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)


class RagIndex:
    def __init__(self, repo: Repository, client: OllamaClient) -> None:
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
        results = self._repo.search_notes_by_embedding(query_blob, top_k)
        logger.info(f"Found {len(results)} matching notes")
        if results:
            for i, res in enumerate(results[:3]):
                logger.debug(
                    f"  Result {i + 1}: id={res.get('id')}, "
                    f"title='{res.get('title', '')[:50]}', "
                    f"distance={res.get('cosine_distance', 'N/A')}"
                )
        return results

    # -- helpers -------------------------------------------------------------

    def _note_text(self, note: dict) -> str:
        title = note.get("title", "")
        content = note.get("content", "")
        return f"{title}\n\n{content}".strip()
