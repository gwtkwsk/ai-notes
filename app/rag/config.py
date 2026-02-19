import os

TOP_K = int(os.getenv("RAG_TOP_K", "5"))
CHUNK_MAX_CHARS = int(os.getenv("RAG_CHUNK_MAX_CHARS", "2000"))
CHUNK_SELECTION_ENABLED: bool = (
    os.getenv("RAG_CHUNK_SELECTION_ENABLED", "false").lower() == "true"
)
