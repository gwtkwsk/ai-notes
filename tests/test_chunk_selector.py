"""Tests for the chunk selection RAG module."""

from __future__ import annotations

from collections.abc import Generator

from app.rag.chunk_selector import SELECTION_CHUNK_MAX_CHARS, ChunkSelector


class FakeLLMClient:
    """Fake LLM client returning configurable YES/NO responses based on keywords."""

    def __init__(
        self, keyword_responses: dict[str, str] | None = None, default: str = "NO"
    ) -> None:
        self._keyword_responses = keyword_responses or {}
        self._default = default
        self.call_count = 0

    def embed(self, text: str) -> list[float]:
        return [0.0]

    def generate(self, prompt: str, system: str | None = None) -> str:
        self.call_count += 1
        # Match keywords only in the Text chunk section to avoid matching keywords
        # that appear in the question itself.
        search_text = prompt
        if "Text chunk:" in prompt:
            search_text = prompt.split("Text chunk:")[1]
        for keyword, response in self._keyword_responses.items():
            if keyword in search_text:
                return response
        return self._default

    def generate_stream(
        self, prompt: str, system: str | None = None
    ) -> Generator[str, None, None]:
        return
        yield  # make it a generator

    def check_connection(self) -> tuple[bool, str]:
        return True, "ok"


class ErrorLLMClient:
    """LLM client that always raises an exception."""

    def embed(self, text: str) -> list[float]:
        return [0.0]

    def generate(self, prompt: str, system: str | None = None) -> str:
        raise RuntimeError("LLM connection failed")

    def generate_stream(
        self, prompt: str, system: str | None = None
    ) -> Generator[str, None, None]:
        return
        yield

    def check_connection(self) -> tuple[bool, str]:
        return False, "error"


class CapturingFakeLLMClient:
    """LLM client that records the last prompt it received."""

    def __init__(self, default: str = "YES") -> None:
        self._default = default
        self.last_prompt: str = ""
        self.last_system: str | None = None

    def embed(self, text: str) -> list[float]:
        return [0.0]

    def generate(self, prompt: str, system: str | None = None) -> str:
        self.last_prompt = prompt
        self.last_system = system
        return self._default

    def generate_stream(
        self, prompt: str, system: str | None = None
    ) -> Generator[str, None, None]:
        return
        yield  # make it a generator

    def check_connection(self) -> tuple[bool, str]:
        return True, "ok"


def make_chunk(title: str, content: str) -> dict:
    return {"id": 1, "title": title, "content": content}


class TestIsRelevant:
    def test_yes_response_returns_true(self) -> None:
        client = FakeLLMClient(default="YES")
        selector = ChunkSelector(client)
        chunk = make_chunk("Note", "Some content about Python")
        assert selector.is_relevant(chunk, "What is Python?") is True

    def test_no_response_returns_false(self) -> None:
        client = FakeLLMClient(default="NO")
        selector = ChunkSelector(client)
        chunk = make_chunk("Note", "Some content about cooking")
        assert selector.is_relevant(chunk, "What is Python?") is False

    def test_case_insensitive_yes(self) -> None:
        for response in ["yes", "Yes", "YES", " yes\n", "yes, definitely"]:
            client = FakeLLMClient(default=response)
            selector = ChunkSelector(client)
            chunk = make_chunk("Note", "content")
            assert selector.is_relevant(chunk, "question?") is True, (
                f"Failed for response: {response!r}"
            )

    def test_case_insensitive_no(self) -> None:
        for response in ["no", "No", "NO", " no\n", "no, not relevant"]:
            client = FakeLLMClient(default=response)
            selector = ChunkSelector(client)
            chunk = make_chunk("Note", "content")
            assert selector.is_relevant(chunk, "question?") is False, (
                f"Failed for response: {response!r}"
            )

    def test_llm_error_defaults_to_true(self) -> None:
        """On LLM error, chunk should be kept (fail-open) to avoid silent data loss."""
        client = ErrorLLMClient()
        selector = ChunkSelector(client)
        chunk = make_chunk("Note", "Some content")
        assert selector.is_relevant(chunk, "question?") is True

    def test_empty_response_defaults_to_false(self) -> None:
        client = FakeLLMClient(default="")
        selector = ChunkSelector(client)
        chunk = make_chunk("Note", "content")
        assert selector.is_relevant(chunk, "question?") is False

    def test_content_truncated_to_selection_limit(self) -> None:
        """Content longer than SELECTION_CHUNK_MAX_CHARS is truncated before LLM."""
        capturing_client = CapturingFakeLLMClient(default="YES")
        selector = ChunkSelector(capturing_client)
        long_content = "A" * (SELECTION_CHUNK_MAX_CHARS + 500)
        chunk = make_chunk("Long Note", long_content)
        selector.is_relevant(chunk, "question?")
        # The prompt must contain the truncated content (exactly 1500 A's)
        assert "A" * SELECTION_CHUNK_MAX_CHARS in capturing_client.last_prompt
        assert "A" * (SELECTION_CHUNK_MAX_CHARS + 1) not in capturing_client.last_prompt

    def test_missing_content_key_does_not_raise(self) -> None:
        """A chunk dict with no 'content' key should not raise an exception."""
        client = FakeLLMClient(default="YES")
        selector = ChunkSelector(client)
        chunk = {"id": 1, "title": "Note without content"}
        result = selector.is_relevant(chunk, "question?")
        assert isinstance(result, bool)


class TestSelect:
    def test_filters_irrelevant_chunks(self) -> None:
        client = FakeLLMClient(
            keyword_responses={"Python": "YES", "cooking": "NO"},
            default="NO",
        )
        selector = ChunkSelector(client)
        chunks = [
            make_chunk("Python Tips", "Python is great"),
            make_chunk("Cooking Guide", "How to cook pasta"),
            make_chunk("Python Basics", "Learn Python programming"),
        ]
        result = selector.select(chunks, "How do I use Python?")
        assert len(result) == 2
        titles = [c["title"] for c in result]
        assert "Python Tips" in titles
        assert "Python Basics" in titles
        assert "Cooking Guide" not in titles

    def test_empty_input_returns_empty(self) -> None:
        client = FakeLLMClient(default="YES")
        selector = ChunkSelector(client)
        result = selector.select([], "question?")
        assert result == []
        assert client.call_count == 0  # No LLM calls for empty input

    def test_all_relevant(self) -> None:
        client = FakeLLMClient(default="YES")
        selector = ChunkSelector(client)
        chunks = [make_chunk(f"Note {i}", f"content {i}") for i in range(3)]
        result = selector.select(chunks, "question?")
        assert len(result) == 3

    def test_all_filtered(self) -> None:
        client = FakeLLMClient(default="NO")
        selector = ChunkSelector(client)
        chunks = [make_chunk(f"Note {i}", f"content {i}") for i in range(3)]
        result = selector.select(chunks, "question?")
        assert result == []

    def test_preserves_chunk_data(self) -> None:
        """Returned chunks should be identical to the input dicts."""
        client = FakeLLMClient(default="YES")
        selector = ChunkSelector(client)
        chunk = {"id": 42, "title": "My Note", "content": "My content", "extra": "data"}
        result = selector.select([chunk], "question?")
        assert len(result) == 1
        assert result[0] is chunk  # Same object, not a copy

    def test_error_in_llm_keeps_chunk(self) -> None:
        """If LLM errors on a chunk, it should be kept (fail-open)."""
        client = ErrorLLMClient()
        selector = ChunkSelector(client)
        chunks = [make_chunk("Note", "content")]
        result = selector.select(chunks, "question?")
        assert len(result) == 1

    def test_llm_called_once_per_chunk(self) -> None:
        """select() must call the LLM exactly once per chunk."""
        client = FakeLLMClient(default="YES")
        selector = ChunkSelector(client)
        chunks = [make_chunk(f"Note {i}", f"content {i}") for i in range(4)]
        selector.select(chunks, "question?")
        assert client.call_count == len(chunks)


class TestSelectWithResults:
    def test_returns_correct_structure(self) -> None:
        client = FakeLLMClient(
            keyword_responses={"Python": "YES", "cooking": "NO"},
            default="NO",
        )
        selector = ChunkSelector(client)
        chunks = [
            make_chunk("Python Tips", "Python is great"),
            make_chunk("Cooking Guide", "How to cook pasta"),
        ]
        results = selector.select_with_results(chunks, "Python question?")

        assert len(results) == 2
        # Check TypedDict keys
        for r in results:
            assert "chunk" in r
            assert "relevant" in r
            assert "reason" in r

        python_result = next(r for r in results if r["chunk"]["title"] == "Python Tips")
        assert python_result["relevant"] is True
        assert python_result["reason"] != ""

        cooking_result = next(
            r for r in results if r["chunk"]["title"] == "Cooking Guide"
        )
        assert cooking_result["relevant"] is False

    def test_empty_input(self) -> None:
        client = FakeLLMClient(default="YES")
        selector = ChunkSelector(client)
        results = selector.select_with_results([], "question?")
        assert results == []

    def test_llm_error_marks_relevant_with_reason(self) -> None:
        client = ErrorLLMClient()
        selector = ChunkSelector(client)
        chunk = make_chunk("Note", "content")
        results = selector.select_with_results([chunk], "question?")
        assert len(results) == 1
        assert results[0]["relevant"] is True
        assert "error" in results[0]["reason"].lower()

    def test_all_relevant(self) -> None:
        """All YES responses: every result should have relevant=True."""
        client = FakeLLMClient(default="YES")
        selector = ChunkSelector(client)
        chunks = [make_chunk(f"Note {i}", f"content {i}") for i in range(3)]
        results = selector.select_with_results(chunks, "question?")
        assert len(results) == 3
        assert all(r["relevant"] is True for r in results)

    def test_all_filtered(self) -> None:
        """All NO responses: every result should have relevant=False."""
        client = FakeLLMClient(default="NO")
        selector = ChunkSelector(client)
        chunks = [make_chunk(f"Note {i}", f"content {i}") for i in range(3)]
        results = selector.select_with_results(chunks, "question?")
        assert len(results) == 3
        assert all(r["relevant"] is False for r in results)
