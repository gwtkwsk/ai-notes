from __future__ import annotations

from collections.abc import Generator
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def embed(self, text: str) -> list[float]: ...

    def generate(self, prompt: str, system: str | None = None) -> str: ...

    def generate_stream(
        self, prompt: str, system: str | None = None
    ) -> Generator[str, None, None]: ...

    def check_connection(self) -> tuple[bool, str]: ...
