from __future__ import annotations

import json
from collections.abc import Callable

from app.data.repository import Repository
from app.rag.config import TOP_K
from app.rag.ollama_client import OllamaClient


class RagIndex:
    def __init__(self, repo: Repository, client: OllamaClient) -> None:
        self._repo = repo
        self._client = client

    def build_index(
        self,
        progress_cb: Callable[[int, int, dict], None] | None = None,
    ) -> int:
        notes = self._repo.list_notes_for_embedding()
        total = len(notes)
        self._repo.clear_embeddings()
        for idx, note in enumerate(notes, start=1):
            text = self._note_text(note)
            vector = self._client.embed(text)
            self._repo.upsert_note_embedding(note["id"], json.dumps(vector))
            if progress_cb is not None:
                progress_cb(idx, total, note)
        return total

    def query(
        self,
        question: str,
        top_k: int = TOP_K,
        status_cb: Callable[[str], None] | None = None,
    ) -> list[dict]:
        if status_cb is not None:
            status_cb("Embedding the question")
        q_vec = self._client.embed(question)
        if not q_vec:
            return []
        if status_cb is not None:
            status_cb("Searching notes")
        return self._repo.search_notes_by_embedding(json.dumps(q_vec), top_k)

    def _note_text(self, note: dict) -> str:
        title = note.get("title", "")
        content = note.get("content", "")
        return f"{title}\n\n{content}".strip()
