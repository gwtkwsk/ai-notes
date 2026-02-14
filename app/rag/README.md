# RAG (Ollama + LangGraph)

Config via env vars:

- OLLAMA_BASE_URL (default `http://localhost:11434`)
- OLLAMA_EMBED_MODEL (default `qwen3-embedding:8b`)
- OLLAMA_LLM_MODEL (default `qwen2.5:7b`)
- RAG_TOP_K (default `5`)
- RAG_CHUNK_MAX_CHARS (default `2000`)

## Storage

Embeddings are stored as binary BLOB (little-endian float32) in `note_embeddings` table.
Long notes are automatically split into chunks at markdown heading boundaries for better semantic search accuracy.
