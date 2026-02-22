from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

from app.data.repository import Repository
from app.rag.index import RagIndex


class FakeOllama:
    def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "python" in lowered:
            return [1.0, 0.0, 0.0]
        if "sql" in lowered or "sqlite" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    def generate(self, prompt: str, system: str | None = None) -> str:
        return "ok"

    def generate_stream(
        self, prompt: str, system: str | None = None
    ) -> Generator[str, None, None]:
        return
        yield  # make it a generator

    def check_connection(self) -> tuple[bool, str]:
        return True, "ok"


def test_build_index_and_query(tmp_path: Path) -> None:
    repo = Repository(str(tmp_path / "notes.db"))
    note_id = repo.create_note("Python note", "Python tips")
    other_id = repo.create_note("SQL note", "SQLite basics")
    index = RagIndex(repo, FakeOllama())

    index.build_index()
    notes = repo.list_notes_with_embeddings()
    stored = [n for n in notes if n["id"] == note_id][0]
    assert stored["embedding_count"] >= 1

    results = index.query("python question", top_k=1)
    assert len(results) == 1
    assert results[0]["id"] == note_id

    sql_results = index.query("sql question", top_k=1)
    assert len(sql_results) == 1
    assert sql_results[0]["id"] == other_id

    repo.close()


def test_chunking_short_text() -> None:
    """Short text should produce a single chunk."""
    chunks = RagIndex._chunk_text("Short note")
    assert chunks == ["Short note"]


def test_chunking_empty_text() -> None:
    """Empty text returns no chunks."""
    chunks = RagIndex._chunk_text("")
    assert chunks == []
    chunks = RagIndex._chunk_text("   ")
    assert chunks == []


def test_chunking_long_markdown() -> None:
    """Long markdown text should split at headings."""
    sections = [
        "# Introduction\n\nSome intro text here.",
        "## Section A\n\nDetails about section A " + "x" * 1500,
        "## Section B\n\nDetails about section B " + "y" * 1500,
    ]
    text = "\n\n".join(sections)
    chunks = RagIndex._chunk_text(text, max_chars=1000)
    assert len(chunks) >= 2
    combined = "\n\n".join(chunks)
    assert "Introduction" in combined
    assert "Section A" in combined
    assert "Section B" in combined


def test_chunking_merges_small_sections() -> None:
    """Tiny adjacent sections should be merged."""
    text = "# A\n\nSmall.\n\n## B\n\nAlso small."
    chunks = RagIndex._chunk_text(text, max_chars=5000)
    assert len(chunks) == 1
    assert "Small." in chunks[0]
    assert "Also small." in chunks[0]


def test_chunking_no_headings_paragraphs() -> None:
    """Long text without headings should split on paragraphs."""
    paragraphs = [f"Paragraph {i}. " + "w" * 800 for i in range(5)]
    text = "\n\n".join(paragraphs)
    chunks = RagIndex._chunk_text(text, max_chars=1000)
    assert len(chunks) >= 2


class _FakeExpander:
    def __init__(self, values: list[str] | None = None, raises: bool = False) -> None:
        self._values = values or []
        self._raises = raises

    def expand(self, question: str, target_count: int) -> list[str]:
        if self._raises:
            raise RuntimeError("expander error")
        return self._values


class _FakeClientForQuery:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self.embed_calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return self._vectors.get(text, [])

    def generate(self, prompt: str, system: str | None = None) -> str:
        return ""

    def generate_stream(
        self, prompt: str, system: str | None = None
    ) -> Generator[str, None, None]:
        return
        yield

    def check_connection(self) -> tuple[bool, str]:
        return True, "ok"


class _FakeRepoForQuery:
    def __init__(
        self,
        vector_results: dict[bytes, list[dict]],
        bm25_results: dict[str, list[dict]],
    ) -> None:
        self._vector_results = vector_results
        self._bm25_results = bm25_results
        self.embedding_calls: list[bytes] = []
        self.bm25_calls: list[str] = []

    def search_notes_by_embedding(self, query_vector: bytes, top_k: int) -> list[dict]:
        self.embedding_calls.append(query_vector)
        return self._vector_results.get(query_vector, [])[:top_k]

    def search_notes_by_bm25(self, query: str, top_k: int) -> list[dict]:
        self.bm25_calls.append(query)
        return self._bm25_results.get(query, [])[:top_k]

    def get_best_chunk_text(self, note_id: int, query_vector: bytes) -> str:
        return f"chunk-{note_id}"


def _doc(note_id: int) -> dict:
    return {"id": note_id, "title": f"n{note_id}", "content": f"c{note_id}"}


def test_query_multi_query_executes_multiple_legs_and_fuses_deterministically() -> None:
    client = _FakeClientForQuery(
        {
            "q1": [1.0, 0.0],
            "q2": [2.0, 0.0],
        }
    )
    q1_blob = RagIndex._serialize_vector([1.0, 0.0])
    q2_blob = RagIndex._serialize_vector([2.0, 0.0])

    repo = _FakeRepoForQuery(
        vector_results={
            q1_blob: [_doc(1), _doc(3)],
            q2_blob: [_doc(2)],
        },
        bm25_results={
            "q1": [_doc(1)],
            "q2": [_doc(1), _doc(2)],
        },
    )
    index = RagIndex(
        repo=cast(Any, repo),
        client=cast(Any, client),
        query_expander=cast(Any, _FakeExpander(["q1", "q2"])),
    )

    results = index.query("base", top_k=3, transformed_query_count=2, hybrid=True)

    assert len(repo.embedding_calls) == 2
    assert repo.bm25_calls == ["q1", "q2"]
    assert [r["id"] for r in results] == [1, 2, 3]


def test_query_expander_empty_or_error_fallback_to_original() -> None:
    client = _FakeClientForQuery({"base": [1.0, 0.0]})
    base_blob = RagIndex._serialize_vector([1.0, 0.0])
    repo = _FakeRepoForQuery(
        vector_results={base_blob: [_doc(10)]},
        bm25_results={"base": [_doc(10)]},
    )

    index_empty = RagIndex(
        repo=cast(Any, repo),
        client=cast(Any, client),
        query_expander=cast(Any, _FakeExpander([])),
    )
    results_empty = index_empty.query("base", top_k=1, transformed_query_count=4)
    assert results_empty[0]["id"] == 10
    assert client.embed_calls[-1] == "base"

    index_error = RagIndex(
        repo=cast(Any, repo),
        client=cast(Any, client),
        query_expander=cast(Any, _FakeExpander(raises=True)),
    )
    results_error = index_error.query("base", top_k=1, transformed_query_count=4)
    assert results_error[0]["id"] == 10
    assert client.embed_calls[-1] == "base"


def test_query_partial_embed_failure_skips_failed_leg() -> None:
    client = _FakeClientForQuery(
        {
            "q1": [1.0, 0.0],
            "q3": [3.0, 0.0],
        }
    )
    q1_blob = RagIndex._serialize_vector([1.0, 0.0])
    q3_blob = RagIndex._serialize_vector([3.0, 0.0])
    repo = _FakeRepoForQuery(
        vector_results={q1_blob: [_doc(1)], q3_blob: [_doc(3)]},
        bm25_results={"q1": [_doc(1)], "q3": [_doc(3)]},
    )

    index = RagIndex(
        repo=cast(Any, repo),
        client=cast(Any, client),
        query_expander=cast(Any, _FakeExpander(["q1", "q2", "q3"])),
    )
    results = index.query("base", top_k=2, transformed_query_count=3, hybrid=True)

    assert "q2" in client.embed_calls
    assert repo.bm25_calls == ["q1", "q3"]
    assert [r["id"] for r in results] == [1, 3]


def test_query_accepts_use_hybrid_keyword_for_backward_compatibility() -> None:
    client = _FakeClientForQuery({"base": [1.0, 0.0]})
    base_blob = RagIndex._serialize_vector([1.0, 0.0])
    repo = _FakeRepoForQuery(
        vector_results={base_blob: [_doc(7)]},
        bm25_results={"base": [_doc(7)]},
    )
    index = RagIndex(
        repo=cast(Any, repo),
        client=cast(Any, client),
        query_expander=cast(Any, _FakeExpander(["base"])),
    )

    results = index.query("base", top_k=1, use_hybrid=False)

    assert [r["id"] for r in results] == [7]
    assert repo.bm25_calls == []
