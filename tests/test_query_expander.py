from __future__ import annotations

from collections.abc import Generator

from app.rag.query_expander import QueryExpander


class _FakeClient:
    def __init__(self, response: str = "", should_raise: bool = False) -> None:
        self._response = response
        self._should_raise = should_raise
        self.last_prompt = ""

    def embed(self, text: str) -> list[float]:
        return [1.0]

    def generate(self, prompt: str, system: str | None = None) -> str:
        if self._should_raise:
            raise RuntimeError("boom")
        self.last_prompt = prompt
        return self._response

    def generate_stream(
        self, prompt: str, system: str | None = None
    ) -> Generator[str, None, None]:
        return
        yield

    def check_connection(self) -> tuple[bool, str]:
        return True, "ok"


def test_parse_output_to_query_list() -> None:
    client = _FakeClient(response="1. Python sqlite\n- python vectors\n  foo bar  ")
    expander = QueryExpander(client)

    expanded = expander.expand("Python search", target_count=4)

    assert expanded == ["Python search", "Python sqlite", "python vectors", "foo bar"]


def test_stable_case_insensitive_dedupe() -> None:
    client = _FakeClient(response="Foo\nfoo\nFOO\nBar")
    expander = QueryExpander(client)

    expanded = expander.expand("foo", target_count=5)

    assert expanded == ["foo", "Bar"]


def test_empty_or_error_falls_back_to_original() -> None:
    empty_client = _FakeClient(response="   ")
    error_client = _FakeClient(should_raise=True)

    assert QueryExpander(empty_client).expand("hello world", target_count=3) == [
        "hello world"
    ]
    assert QueryExpander(error_client).expand("hello world", target_count=3) == [
        "hello world"
    ]


def test_target_count_clamp_enforced() -> None:
    client = _FakeClient(response="a\nb\nc\nd\ne\nf\ng\nh\ni\nj")
    expander = QueryExpander(client)

    expanded = expander.expand("base", target_count=99)

    assert len(expanded) == 8
    assert expanded[0] == "base"


def test_prompt_explicitly_requires_intent_preservation() -> None:
    client = _FakeClient(response="alt query")
    expander = QueryExpander(client)

    expander.expand("original question", target_count=2)

    assert "Preserve the original meaning and user intent exactly" in client.last_prompt
