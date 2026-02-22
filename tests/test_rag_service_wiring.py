from __future__ import annotations

from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, cast

import pytest

from app.config import Config
from app.rag.service import RagService


class _FakeRepo:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def close(self) -> None:
        return


class _FakeClient:
    def embed(self, text: str) -> list[float]:
        return [1.0]

    def generate(self, prompt: str, system: str | None = None) -> str:
        return "ok"

    def generate_stream(
        self, prompt: str, system: str | None = None
    ) -> Generator[str, None, None]:
        yield "ok"

    def check_connection(self) -> tuple[bool, str]:
        return True, "ok"


class _FakeRagIndex:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.query_calls: list[dict] = []

    def build_index(
        self,
        progress_cb: Callable[[int, int, dict], None] | None = None,
    ) -> int:
        return 0

    def index_note(self, note_id: int) -> bool:
        return True

    def query(
        self,
        question: str,
        top_k: int = 5,
        transformed_query_count: int = 1,
        hybrid: bool | None = None,
        use_hybrid: bool | None = None,
        status_cb: Callable[[str], None] | None = None,
    ) -> list[dict]:
        self.query_calls.append(
            {
                "question": question,
                "top_k": top_k,
                "transformed_query_count": transformed_query_count,
                "hybrid": hybrid,
                "use_hybrid": use_hybrid,
            }
        )
        return [{"id": 1, "title": "n1", "content": "c1"}]


def test_ask_stream_uses_saved_transformed_query_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "config.json"
    config = Config(config_path=config_file)
    config.set_rag_transformed_query_count(6)
    config.save()

    reloaded = Config(config_path=config_file)

    monkeypatch.setattr("app.rag.service.create_llm_client", lambda _cfg: _FakeClient())
    monkeypatch.setattr("app.rag.service.RagIndex", _FakeRagIndex)

    service = RagService(cast(Any, _FakeRepo(str(tmp_path / "notes.db"))), reloaded)
    list(service.ask_stream("hello"))

    fake_index = service._index
    assert isinstance(fake_index, _FakeRagIndex)
    assert fake_index.query_calls
    assert fake_index.query_calls[0]["transformed_query_count"] == 6
