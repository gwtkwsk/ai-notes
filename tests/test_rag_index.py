import json

from app.data.repository import Repository
from app.rag.index import RagIndex
from app.rag.ollama_client import OllamaClient


class FakeOllama(OllamaClient):
    def __init__(self):
        pass

    def embed(self, text: str):
        lowered = text.lower()
        if "python" in lowered:
            return [1.0, 0.0, 0.0]
        if "sql" in lowered or "sqlite" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    def generate(self, prompt: str, system: str | None = None) -> str:
        return "ok"


def test_build_index_and_query(tmp_path):
    repo = Repository(str(tmp_path / "notes.db"))
    note_id = repo.create_note("Python note", "Python tips")
    other_id = repo.create_note("SQL note", "SQLite basics")
    index = RagIndex(repo, FakeOllama())

    index.build_index()
    notes = repo.list_notes_with_embeddings()
    stored = [n for n in notes if n["id"] == note_id][0]
    vector = json.loads(stored["vector_json"])
    assert vector

    results = index.query("python question", top_k=1)
    assert len(results) == 1
    assert results[0]["id"] == note_id

    sql_results = index.query("sql question", top_k=1)
    assert len(sql_results) == 1
    assert sql_results[0]["id"] == other_id

    repo.close()
