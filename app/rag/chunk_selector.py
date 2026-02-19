"""Chunk selection module for Modular RAG Architecture.

This module implements the chunk selection pattern: after vector search retrieves
candidate chunks, each chunk is individually evaluated by an LLM to determine
relevance to the question. Irrelevant chunks are filtered out before generation.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from app.rag.llm_client import LLMClient
from app.rag.prompts import build_chunk_relevance_prompt

logger = logging.getLogger(__name__)

# Intentionally smaller than CHUNK_MAX_CHARS (2000) used for generation.
# Yes/no relevance evaluation works well with shorter snippets and avoids
# overloading the context window during the selection phase.
SELECTION_CHUNK_MAX_CHARS = 1500


class ChunkSelectionResult(TypedDict):
    chunk: dict[str, Any]
    relevant: bool
    reason: str


class ChunkSelector:
    """Evaluates chunks for relevance to a question using an LLM.

    This implements the selection pattern from Modular RAG Architecture:
    each retrieved chunk is individually assessed for relevance before
    being passed to the final answer generation step.
    """

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def _parse_response(self, response: str) -> bool:
        """Parse an LLM yes/no response into a boolean.

        Returns False for an empty response (the model replied with nothing
        recognisably relevant). This is distinct from an LLM *error* (e.g.
        a connectivity failure), which is handled by callers with fail-open
        semantics to avoid silent data loss.

        Args:
            response: Raw LLM response string.

        Returns:
            True if the response indicates YES, False otherwise.
        """
        if not response.strip():
            # Empty string: the model returned something but not recognisably
            # relevant. Treat as NOT relevant (fail-closed for empty output).
            # Contrast with LLM errors (exceptions), which use fail-open to
            # avoid silently dropping content on connectivity issues.
            return False
        first_word = response.strip().split()[0].strip(".,!?;:").upper()
        return first_word == "YES"

    def is_relevant(self, chunk: dict[str, Any], question: str) -> bool:
        """Check if a single chunk is relevant to the question.

        Calls the LLM with a yes/no relevance prompt. On LLM error,
        defaults to True (fail-open) to avoid silently dropping content.

        Args:
            chunk: Note dict with 'content' and 'title' fields.
            question: The user's question.

        Returns:
            True if the chunk is relevant, False otherwise.
        """
        content = chunk.get("content", "")[:SELECTION_CHUNK_MAX_CHARS]
        system, user = build_chunk_relevance_prompt(content, question)
        try:
            response = self._client.generate(user, system=system)
            return self._parse_response(response)
        except Exception:
            # Fail-open on LLM errors (e.g. connectivity issues) to avoid
            # silently dropping content. An empty/unrecognised response is
            # handled via _parse_response as False (model replied but said
            # nothing that looks like YES).
            logger.warning(
                "LLM error during chunk relevance check for chunk '%s';"
                " defaulting to relevant",
                chunk.get("title", "unknown"),
                exc_info=True,
            )
            return True

    def select(
        self, chunks: list[dict[str, Any]], question: str
    ) -> list[dict[str, Any]]:
        """Filter chunks, keeping only those relevant to the question.

        Args:
            chunks: List of note dicts from vector search.
            question: The user's question.

        Returns:
            Subset of chunks deemed relevant by the LLM.
        """
        if not chunks:
            return []
        relevant = [c for c in chunks if self.is_relevant(c, question)]
        logger.info(
            "Chunk selection: %d/%d chunks relevant to question",
            len(relevant),
            len(chunks),
        )
        return relevant

    def select_with_results(
        self, chunks: list[dict[str, Any]], question: str
    ) -> list[ChunkSelectionResult]:
        """Evaluate chunks and return full selection results including reasoning.

        Useful for debugging, logging, and testing.

        Args:
            chunks: List of note dicts from vector search.
            question: The user's question.

        Returns:
            List of ChunkSelectionResult dicts with chunk, relevant flag, and reason.
        """
        results: list[ChunkSelectionResult] = []
        for chunk in chunks:
            content = chunk.get("content", "")[:SELECTION_CHUNK_MAX_CHARS]
            system, user = build_chunk_relevance_prompt(content, question)
            try:
                response = self._client.generate(user, system=system)
                relevant = self._parse_response(response)
                reason = response.strip()
            except Exception:
                # Fail-open on LLM errors (e.g. connectivity issues) to avoid
                # silently dropping content. An empty/unrecognised response is
                # handled via _parse_response as False (model replied but said
                # nothing that looks like YES).
                logger.warning(
                    "LLM error during chunk relevance check for chunk '%s';"
                    " defaulting to relevant",
                    chunk.get("title", "unknown"),
                    exc_info=True,
                )
                relevant = True
                reason = "LLM error; defaulted to relevant"
            results.append({"chunk": chunk, "relevant": relevant, "reason": reason})
        return results
