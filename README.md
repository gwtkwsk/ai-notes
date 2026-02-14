# Disco Notes (MVP)

Native GNOME notes app (GTK4/Libadwaita) with local SQLite, Markdown notes, tags, and Q&A over notes using RAG + Ollama.

## Features

- Native GNOME desktop UI (Libadwaita)
- Create, view, and edit notes in Markdown
- Tag notes and filter by multiple tags (AND)
- Ask questions about your notes (RAG + Ollama)
- Local SQLite storage

## Local Development (Fedora GNOME)

**For day-to-day development, run the app directly without building a Flatpak.** Changes take effect immediately on restart.

Install system dependencies (one-time):

```bash
sudo dnf install -y python3-gobject gtk4 libadwaita
```

Install Python dependencies (one-time):

```bash
uv sync --extra dev
```

Run the app:

```bash
python3 desktop.py
```

The app stores data in:

```text
~/.local/share/disco-notes/notes.db
```

You can override the database location:

```bash
DISCO_NOTES_DB=/path/to/notes.db python3 desktop.py
```

**Note:** If you run `python3 desktop.py` outside the `uv` environment, ensure that interpreter also has `sqlite-vec` available (required for RAG search)

## Ollama (required for Q&A)

Run Ollama and pull models used by the app:

```bash
ollama serve
ollama pull nomic-embed-text
ollama pull qwen2.5:7b
```

Model and endpoint settings are in:

- `app/rag/config.py`

## Build Flatpak (Distribution)

**Only needed for creating distributable packages or testing the sandboxed version.** Not required for local development.

Build and install as a Flatpak:

```bash
./scripts/build-flatpak.sh
```

This will:
- Download all Python dependencies as pre-built wheels
- Build the app with the GNOME SDK 48 (Python 3.12)
- Create `disco-notes.flatpak` bundle for distribution
- Install it locally for testing

Run the Flatpak:

```bash
flatpak run org.disco.DiscoNotes
```

The Flatpak stores data in:

```text
~/.var/app/org.disco.DiscoNotes/data/disco-notes/notes.db
```

To uninstall:

```bash
flatpak uninstall org.disco.DiscoNotes
```

## Tests

```bash
uv lock
uv sync --extra dev
uv run python -m pytest
```
