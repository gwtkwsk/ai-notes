from collections.abc import Generator
from pathlib import Path

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
