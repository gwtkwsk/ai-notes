"""Tests for BLOB-based embedding storage with realistic high-dimensional vectors.

These tests validate that Repository and RagIndex correctly handle embeddings
stored as binary float32 BLOBs — including 768-dim and 4096-dim vectors on
file-backed databases (reproducing the scenario that failed with JSON TEXT).
"""

import random
import struct
from pathlib import Path

from app.data.repository import Repository
from app.rag.index import RagIndex
from app.rag.ollama_client import OllamaClient

from .test_helpers import random_vec, to_blob

# ---------------------------------------------------------------------------
# Repository: BLOB storage tests
# ---------------------------------------------------------------------------


class TestRepositoryBlobEmbeddings:
    """Repository must accept bytes (BLOB) for embeddings."""

    def test_store_and_search_3_dim(self, tmp_path: Path) -> None:
        repo = Repository(str(tmp_path / "test.db"))
        nid = repo.create_note("Python", "Tips")
        repo.replace_note_embeddings(nid, [("Tips", to_blob([1.0, 0.0, 0.0]))])

        results = repo.search_notes_by_embedding(to_blob([0.9, 0.1, 0.0]), top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == nid
        repo.close()

    def test_store_and_search_768_dim(self, tmp_path: Path) -> None:
        """768 dimensions: typical for nomic-embed-text."""
        repo = Repository(str(tmp_path / "test.db"))
        n1 = repo.create_note("A", "AAA")
        n2 = repo.create_note("B", "BBB")

        v1 = random_vec(768, seed=1)
        v2 = random_vec(768, seed=2)
        repo.replace_note_embeddings(n1, [("AAA", to_blob(v1))])
        repo.replace_note_embeddings(n2, [("BBB", to_blob(v2))])

        query = random_vec(768, seed=1)
        query[0] += 0.001
        results = repo.search_notes_by_embedding(to_blob(query), top_k=2)
        assert len(results) == 2
        assert results[0]["id"] == n1
        repo.close()

    def test_store_and_search_4096_dim(self, tmp_path: Path) -> None:
        """4096 dimensions on file-backed DB — the scenario that failed with JSON."""
        repo = Repository(str(tmp_path / "test.db"))
        n1 = repo.create_note("Note 1", "Content 1")
        n2 = repo.create_note("Note 2", "Content 2")

        v1 = random_vec(4096, seed=10)
        v2 = random_vec(4096, seed=20)
        repo.replace_note_embeddings(n1, [("Content 1", to_blob(v1))])
        repo.replace_note_embeddings(n2, [("Content 2", to_blob(v2))])

        query = random_vec(4096, seed=10)
        results = repo.search_notes_by_embedding(to_blob(query), top_k=2)
        assert len(results) == 2
        assert results[0]["id"] == n1
        repo.close()

    def test_multiple_chunks_per_note(self, tmp_path: Path) -> None:
        repo = Repository(str(tmp_path / "test.db"))
        nid = repo.create_note("Big", "Multi-chunk")

        chunks = [
            ("Part A", to_blob([1.0, 0.0, 0.0])),
            ("Part B", to_blob([0.0, 1.0, 0.0])),
        ]
        repo.replace_note_embeddings(nid, chunks)

        # Searching for either chunk direction should still find the note
        results = repo.search_notes_by_embedding(to_blob([1.0, 0.0, 0.0]), top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == nid

        results = repo.search_notes_by_embedding(to_blob([0.0, 1.0, 0.0]), top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == nid
        repo.close()

    def test_replace_overwrites_chunks(self, tmp_path: Path) -> None:
        repo = Repository(str(tmp_path / "test.db"))
        nid = repo.create_note("X", "Y")

        repo.replace_note_embeddings(nid, [("old", to_blob([1.0, 0.0, 0.0]))])
        repo.replace_note_embeddings(nid, [("new", to_blob([0.0, 1.0, 0.0]))])

        results = repo.search_notes_by_embedding(to_blob([0.0, 1.0, 0.0]), top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == nid
        repo.close()

    def test_clear_embeddings(self, tmp_path: Path) -> None:
        repo = Repository(str(tmp_path / "test.db"))
        nid = repo.create_note("X", "Y")
        repo.replace_note_embeddings(nid, [("Y", to_blob([1.0, 0.0, 0.0]))])
        repo.clear_embeddings()

        results = repo.search_notes_by_embedding(to_blob([1.0, 0.0, 0.0]), top_k=1)
        assert len(results) == 0
        repo.close()

    def test_list_notes_with_embeddings_count(self, tmp_path: Path) -> None:
        repo = Repository(str(tmp_path / "test.db"))
        n1 = repo.create_note("A", "A")
        n2 = repo.create_note("B", "B")

        repo.replace_note_embeddings(
            n1,
            [
                ("c1", to_blob([1.0, 0.0, 0.0])),
                ("c2", to_blob([0.0, 1.0, 0.0])),
            ],
        )
        notes = repo.list_notes_with_embeddings()
        note_a = [n for n in notes if n["id"] == n1][0]
        note_b = [n for n in notes if n["id"] == n2][0]
        assert note_a["embedding_count"] == 2
        assert note_b["embedding_count"] == 0
        repo.close()


# ---------------------------------------------------------------------------
# RagIndex: full integration with BLOB + chunking
# ---------------------------------------------------------------------------


class FakeOllama768(OllamaClient):
    """Fake Ollama returning 768-dim vectors (like nomic-embed-text)."""

    DIM = 768

    def __init__(self) -> None:
        pass

    def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        # Start from a zero vector so topic signals dominate
        vec = [0.0] * self.DIM
        if "python" in lowered:
            vec[0] = 1.0
            vec[1] = 0.5
        elif "sql" in lowered:
            vec[0] = -1.0
            vec[1] = -0.5
        else:
            # Generic — small random noise
            rng = random.Random(hash(lowered) % 100000)
            vec = [rng.uniform(-0.01, 0.01) for _ in range(self.DIM)]
        return vec

    def generate(self, prompt: str, system: str | None = None) -> str:
        return "ok"


class TestRagIndexIntegration:
    def test_build_and_query_768_dim(self, tmp_path: Path) -> None:
        repo = Repository(str(tmp_path / "notes.db"))
        n1 = repo.create_note("Python tips", "Learn Python programming")
        n2 = repo.create_note("SQL guide", "SQLite database basics")

        index = RagIndex(repo, FakeOllama768())
        count = index.build_index()
        assert count == 2

        results = index.query("python question", top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == n1

        results = index.query("sql question", top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == n2
        repo.close()

    def test_build_index_with_many_notes(self, tmp_path: Path) -> None:
        repo = Repository(str(tmp_path / "notes.db"))
        for i in range(10):
            repo.create_note(f"Note {i}", f"Content about topic {i}")

        index = RagIndex(repo, FakeOllama768())
        count = index.build_index()
        assert count == 10

        results = index.query("topic 0", top_k=3)
        assert len(results) == 3
        repo.close()

    def test_chunked_notes_searchable(self, tmp_path: Path) -> None:
        """Long note split into chunks should still be found by search."""
        repo = Repository(str(tmp_path / "notes.db"))
        content = (
            "# Introduction\n\nPython basics.\n\n"
            "## Advanced\n\nPython advanced features. " + "x" * 2000
        )
        nid = repo.create_note("Python guide", content)

        index = RagIndex(repo, FakeOllama768())
        index.build_index()

        notes = repo.list_notes_with_embeddings()
        stored = [n for n in notes if n["id"] == nid][0]
        # Should have multiple chunks due to length
        assert stored["embedding_count"] >= 2

        results = index.query("python", top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == nid
        repo.close()


# ---------------------------------------------------------------------------
# Vector serialization
# ---------------------------------------------------------------------------


class TestSerializeVector:
    def test_roundtrip(self) -> None:
        original = [0.1, -0.5, 1.0, 0.0]
        blob = RagIndex._serialize_vector(original)
        restored = list(struct.unpack(f"<{len(original)}f", blob))
        for a, b in zip(original, restored, strict=True):
            assert abs(a - b) < 1e-6

    def test_size_is_dim_times_4(self) -> None:
        for dim in [3, 768, 4096]:
            blob = RagIndex._serialize_vector([0.0] * dim)
            assert len(blob) == dim * 4
