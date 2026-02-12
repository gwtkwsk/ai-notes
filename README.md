# Disco Notes (MVP)

A minimal desktop notes application with a Tauri shell and a Python (FastAPI) backend.

## Features

- Create, view, edit notes in plain text or Markdown
- Tag notes and filter by multiple tags (AND)
- Markdown preview mode
- Local SQLite storage

## Run (dev)

```bash
uv venv
source .venv/bin/activate
uv lock
uv sync
cd ui
npm install
npm run tauri dev
```

The Tauri app starts the Python backend automatically. If you want to run the API alone:

```bash
uv run python main.py
```

## Tests

```bash
uv lock
uv sync --dev
pytest
```
