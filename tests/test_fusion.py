"""Unit tests for Reciprocal Rank Fusion module.

These tests cover the pure fusion logic and do not require a database.
"""

from __future__ import annotations

from typing import Any

from app.rag.fusion import reciprocal_rank_fusion


def _note(note_id: int, title: str = "") -> dict[str, Any]:
    return {"id": note_id, "title": title or f"Note {note_id}", "content": ""}


class TestReciprocalRankFusion:
    def test_no_ranked_lists_returns_empty(self) -> None:
        assert reciprocal_rank_fusion([]) == []

    def test_empty_lists_returns_empty(self) -> None:
        result = reciprocal_rank_fusion([[], []])
        assert result == []

    def test_single_list_passthrough(self) -> None:
        docs = [_note(1), _note(2), _note(3)]
        result = reciprocal_rank_fusion([docs])
        ids = [d["id"] for d in result]
        assert ids == [1, 2, 3]

    def test_rrf_score_attached(self) -> None:
        docs = [_note(1)]
        result = reciprocal_rank_fusion([docs])
        assert "rrf_score" in result[0]
        assert result[0]["rrf_score"] > 0

    def test_overlap_boosts_document(self) -> None:
        """Documents appearing in both lists should rank higher."""
        list1 = [_note(1), _note(2), _note(3)]
        list2 = [_note(3), _note(4), _note(5)]
        result = reciprocal_rank_fusion([list1, list2])
        # Note 3 appears in both → should rank above notes appearing in only one list
        ids = [d["id"] for d in result]
        assert ids.index(3) < ids.index(4)
        assert ids.index(3) < ids.index(2)

    def test_only_vector_results(self) -> None:
        """If BM25 returns nothing, vector results should still come through."""
        vector = [_note(1), _note(2)]
        result = reciprocal_rank_fusion([vector, []])
        ids = [d["id"] for d in result]
        assert ids == [1, 2]

    def test_only_bm25_results(self) -> None:
        """If vector returns nothing, BM25 results should still come through."""
        bm25 = [_note(10), _note(20)]
        result = reciprocal_rank_fusion([[], bm25])
        ids = [d["id"] for d in result]
        assert ids == [10, 20]

    def test_higher_combined_rank_wins(self) -> None:
        """A doc ranked 1st in both lists beats one ranked 1st in only one."""
        list1 = [_note(1), _note(2)]
        list2 = [_note(1), _note(3)]
        result = reciprocal_rank_fusion([list1, list2])
        assert result[0]["id"] == 1

    def test_custom_k_parameter(self) -> None:
        """Lower k amplifies rank differences."""
        docs = [_note(1), _note(2)]
        result_k60 = reciprocal_rank_fusion([docs], k=60)
        result_k1 = reciprocal_rank_fusion([docs], k=1)
        # Score gap should be larger with k=1
        gap_k60 = result_k60[0]["rrf_score"] - result_k60[1]["rrf_score"]
        gap_k1 = result_k1[0]["rrf_score"] - result_k1[1]["rrf_score"]
        assert gap_k1 > gap_k60

    def test_no_mutation_of_input_docs(self) -> None:
        """Original dicts should not be mutated by fusion."""
        doc = _note(1)
        original_keys = set(doc.keys())
        reciprocal_rank_fusion([[doc]])
        assert set(doc.keys()) == original_keys

    def test_preserves_original_doc_fields(self) -> None:
        """Result dicts should contain all original fields plus rrf_score."""
        doc = {"id": 42, "title": "Test", "content": "hello", "is_markdown": 1}
        result = reciprocal_rank_fusion([[doc]])
        assert result[0]["title"] == "Test"
        assert result[0]["content"] == "hello"
        assert result[0]["is_markdown"] == 1
        assert "rrf_score" in result[0]
