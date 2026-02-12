# Copilot instructions for Disco Notes

## Scope and priorities
- Keep changes surgical and aligned with existing structure; avoid cross-module refactors unless requested.
- Reuse existing abstractions (`Repository`, `RagService`, `RagIndex`) instead of introducing parallel layers.

## Big picture architecture
- `app/data/` is the persistence boundary (SQLite schema + queries): see `app/data/schema.py`, `app/data/repository.py`.
- `app/rag/` is retrieval/generation and Ollama integration: `service.py`, `index.py`, `langgraph_rag.py`, `ollama_client.py`.
- `app/desktop/` is a local GTK client using `Repository` and `RagService` directly.
- Entrypoints: `desktop.py` and script in `pyproject.toml`.

## Critical contracts to preserve
- Tag filtering is AND semantics in `Repository.list_notes(...)` (`HAVING COUNT(DISTINCT ...) = ?`).
- RAG streaming in `app/rag/service.py` splits `<think>...</think>` content into thinking vs answer deltas; do not collapse these channels.

## Developer workflows (documented commands)
- Backend setup/run: `uv venv && source .venv/bin/activate && uv lock && uv sync`
- Tests: `uv sync --extra dev && uv run python -m pytest`
- Desktop app: `python3 desktop.py` (requires system GTK/PyGObject deps from README)

## Project-specific testing patterns
- Prefer focused `pytest` tests near changed behavior.
- Use temporary SQLite files (`tmp_path`) rather than global/local DB state.
- For RAG tests, use deterministic fakes (see `tests/test_rag_index.py`) and avoid real network calls.

## Integration points and known pitfalls
- Canonical local DB path guidance: `~/.local/share/disco-notes/notes.db` (desktop/XDG style).
- RAG model default should follow code in `app/rag/config.py` (`qwen2.5:7b`), even if docs mention older alternatives.

## Change scope guardrails
- Do not introduce new transport layers or extra frontends unless explicitly requested.
- Keep GNOME/Libadwaita UX consistent and avoid unrelated formatting churn.
