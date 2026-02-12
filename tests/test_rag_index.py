import json

from app.data.repository import Repository
from app.rag.index import RagIndex
from app.rag.ollama_client import OllamaClient


class FakeOllama(OllamaClient):
    def __init__(self):
        pass

    def embed(self, text: str):
        return [float(len(text) % 5), 1.0, 0.5]

    def generate(self, prompt: str) -> str:
        return "ok"


def test_build_index_and_query(tmp_path):
    repo = Repository(str(tmp_path / "notes.db"))
    note_id = repo.create_note("Title", "Body")
    index = RagIndex(repo, FakeOllama())

    index.build_index()
    notes = repo.list_notes_with_embeddings()
    stored = [n for n in notes if n["id"] == note_id][0]
    vector = json.loads(stored["vector_json"])
    assert vector

    results = index.query("question")
    assert len(results) == 1

    repo.close()
