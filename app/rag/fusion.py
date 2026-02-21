"""Reciprocal Rank Fusion for hybrid search.

Implements RRF as described in:
    Cormack, Clarke & Buettcher (2009) "Reciprocal Rank Fusion outperforms
    Condorcet and individual Rank Learning Methods"

This module is intentionally dependency-free and easily testable in isolation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    id_key: str = "id",
    k: int = 60,
) -> list[dict[str, Any]]:
    """Fuse multiple ranked result lists using Reciprocal Rank Fusion.

    Each document's RRF score is the sum of 1/(k + rank) across all ranked
    lists that contain it. Documents missing from a list contribute 0 for
    that list. A higher RRF score means better overall ranking.

    Args:
        ranked_lists: Each inner list is a sequence of note dicts ordered
            best-first. Lists may have different lengths and may overlap.
        id_key: Dict key used as the unique document identifier (default "id").
        k: RRF smoothing constant (default 60 from the original paper).
            Larger k makes ranks more uniform; smaller k amplifies top ranks.

    Returns:
        All documents from all ranked lists, sorted by descending RRF score
        (best first). Each returned dict is the original note dict augmented
        with an ``rrf_score`` field (float) for debugging and logging.
    """
    scores: dict[Any, float] = {}
    docs: dict[Any, dict[str, Any]] = {}

    for ranked_list in ranked_lists:
        for rank_0based, doc in enumerate(ranked_list):
            doc_id = doc[id_key]
            if doc_id not in docs:
                docs[doc_id] = doc
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank_0based + 1)

    sorted_ids = sorted(scores, key=lambda d: scores[d], reverse=True)

    result: list[dict[str, Any]] = []
    for doc_id in sorted_ids:
        enriched = dict(docs[doc_id])
        enriched["rrf_score"] = scores[doc_id]
        result.append(enriched)

    logger.debug(
        "RRF fusion: %d input lists → %d unique docs fused",
        len(ranked_lists),
        len(result),
    )
    return result
