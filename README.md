# AI Notes (MVP)

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
uv sync --group dev
```

Run the app:

```bash
python desktop.py
```

The app stores data in:

```text
~/.local/share/ai-notes/notes.db
```

You can override the database location:

```bash
AI_NOTES_DB=/path/to/notes.db python desktop.py
```

**Note:** If you run `python desktop.py` outside the `uv` environment, ensure that interpreter also has `sqlite-vec` available (required for RAG search)

## Ollama (required for Q&A)

Run Ollama and pull models used by the app:

```bash
ollama serve
ollama pull qwen3-embedding:8b
ollama pull qwen3:8b
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
- Create `build/ai-notes.flatpak` bundle for distribution
- Install it locally for testing

Run the Flatpak:

```bash
flatpak run ai.notes.AINotes
```

The Flatpak stores data in:

```text
~/.var/app/ai.notes.AINotes/data/ai-notes/notes.db
```

To uninstall:

```bash
flatpak uninstall ai.notes.AINotes
```

## Tests

```bash
uv run --group dev python -m pytest tests/
```

## Linting

```bash
uv run --group dev ruff check
uv run --group dev ruff format
uv run --group dev pyright
```

## Optional: Vagrant on Fedora Workstation 43

If you want a disposable CLI/dev VM, this repository includes a simple `Vagrantfile` for Fedora Cloud Base 43 using libvirt/KVM.

Fedora Workstation 43 setup:

```bash
sudo dnf install -y @virtualization vagrant vagrant-libvirt
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt "$USER"
newgrp libvirt
sudo virsh net-start default || true
sudo virsh net-autostart default
```

Verify the plugin and provider are available:

```bash
vagrant plugin list | grep vagrant-libvirt
virsh uri
```

Basic usage:

```bash
vagrant up --provider=libvirt
vagrant ssh
vagrant halt
vagrant destroy -f
```

Notes:

- The Vagrantfile uses the official Fedora Cloud Base 43 libvirt box from Fedora downloads via `config.vm.box_url`
- If Fedora republishes the box under a newer point release, override it with `VAGRANT_FEDORA_BOX_URL=... vagrant up --provider=libvirt`
- This setup is intended mainly for command-line development and testing
- It is not meant to be the primary way to run the GNOME desktop app UI inside the VM

### Using GitHub Copilot CLI inside the VM

The `Vagrantfile` supports routing Copilot CLI traffic through a host-side
mitmproxy so that the real GitHub token never leaves the host.  The proxy
intercepts requests from the VM and injects the real token (retrieved from
GNOME Keyring) transparently.  The VM only stores a harmless placeholder token
and trusts the mitmproxy CA certificate.

See **[docs/vagrant-copilot-proxy.md](docs/vagrant-copilot-proxy.md)** for
the full setup guide, including GNOME Keyring configuration, the mitmproxy
injection script template, all supported environment variables, and a manual
validation flow.
