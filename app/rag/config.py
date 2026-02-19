import os

TOP_K = int(os.getenv("RAG_TOP_K", "5"))
CHUNK_MAX_CHARS = int(os.getenv("RAG_CHUNK_MAX_CHARS", "2000"))
