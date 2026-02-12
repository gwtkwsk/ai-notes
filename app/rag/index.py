from __future__ import annotations

import json
import math
from typing import Dict, List

from app.data.repository import Repository
from app.rag.config import TOP_K
from app.rag.ollama_client import OllamaClient


class RagIndex:
    def __init__(self, repo: Repository, client: OllamaClient) -> None:
        self._repo = repo
        self._client = client

    def build_index(self, progress_cb=None) -> int:
        notes = self._repo.list_notes_for_embedding()
        total = len(notes)
        for idx, note in enumerate(notes, start=1):
            text = self._note_text(note)
            vector = self._client.embed(text)
            self._repo.upsert_note_embedding(note["id"], json.dumps(vector))
            if progress_cb is not None:
                progress_cb(idx, total, note)
        return total

    def query(self, question: str, top_k: int = TOP_K, status_cb=None) -> List[Dict]:
        if status_cb is not None:
            status_cb("Embedding the question")
        q_vec = self._client.embed(question)
        if not q_vec:
            return []
        if status_cb is not None:
            status_cb("Searching notes")
        notes = self._repo.list_notes_with_embeddings()
        scored = []
        for note in notes:
            vec_json = note.get("vector_json")
            if not vec_json:
                continue
            vec = json.loads(vec_json)
            score = _cosine_similarity(q_vec, vec)
            scored.append({"note": note, "score": score})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return [item["note"] for item in scored[:top_k]]

    def _note_text(self, note: Dict) -> str:
        title = note.get("title", "")
        content = note.get("content", "")
        return f"{title}\n\n{content}".strip()


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(len(a)):
        dot += a[i] * b[i]
        norm_a += a[i] * a[i]
        norm_b += b[i] * b[i]
    if norm_a == 0.0 or norm_b == 0.0:
        return -1.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
