import os

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:8b")
LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "qwen2.5:7b")
TOP_K = int(os.getenv("RAG_TOP_K", "5"))
