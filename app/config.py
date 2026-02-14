"""Configuration management for Disco Notes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


_CONFIG_VERSION = 1


def _default_config_path() -> Path:
    """Get default config file path following XDG spec."""
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "disco-notes" / "config.json"


class Config:
    """Application configuration with persistence."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._path = config_path or _default_config_path()
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load config from disk or return defaults."""
        if not self._path.exists():
            return self._defaults()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Validate version
                if data.get("version") != _CONFIG_VERSION:
                    return self._defaults()
                return data
        except (OSError, json.JSONDecodeError):
            return self._defaults()

    def _defaults(self) -> Dict[str, Any]:
        """Return default configuration."""
        return {
            "version": _CONFIG_VERSION,
            "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            "embed_model": os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:8b"),
            "llm_model": os.getenv("OLLAMA_LLM_MODEL", "qwen2.5:7b"),
            "top_k": int(os.getenv("RAG_TOP_K", "5")),
        }

    def save(self) -> None:
        """Persist config to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError:
            pass  # silently fail – not critical

    # -- Getters with env var fallback --

    @property
    def ollama_base_url(self) -> str:
        return str(self._data.get("ollama_base_url", "http://localhost:11434"))

    @property
    def embed_model(self) -> str:
        return str(self._data.get("embed_model", "qwen3-embedding:8b"))

    @property
    def llm_model(self) -> str:
        return str(self._data.get("llm_model", "qwen2.5:7b"))

    @property
    def top_k(self) -> int:
        return int(self._data.get("top_k", 5))

    # -- Setters --

    def set_ollama_base_url(self, value: str) -> None:
        self._data["ollama_base_url"] = value.strip()

    def set_embed_model(self, value: str) -> None:
        self._data["embed_model"] = value.strip()

    def set_llm_model(self, value: str) -> None:
        self._data["llm_model"] = value.strip()

    def set_top_k(self, value: int) -> None:
        self._data["top_k"] = max(1, int(value))
