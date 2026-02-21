"""Configuration management for AI Notes."""

from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Any

_CONFIG_VERSION = 3


def _default_config_path() -> Path:
    """Get default config file path following XDG spec."""
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "ai-notes" / "config.json"


class LLMProvider(StrEnum):
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"


class Config:
    """Application configuration with persistence."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._path = config_path or _default_config_path()
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        """Load config from disk or return defaults."""
        if not self._path.exists():
            return self._defaults()
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
                data = self._migrate(data)
                # Validate version
                if data.get("version") != _CONFIG_VERSION:
                    return self._defaults()
                return data
        except (OSError, json.JSONDecodeError):
            return self._defaults()

    def _migrate(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("version") == 1:
            data["llm_provider"] = LLMProvider.OLLAMA.value
            data["llm_base_url"] = data.pop("ollama_base_url", "http://localhost:11434")
            data["llm_api_key"] = ""
            data["version"] = 2
        if data.get("version") == 2:
            data["hybrid_search_enabled"] = True
            data["chunk_selection_enabled"] = False
            data["version"] = 3
        return data

    def _defaults(self) -> dict[str, Any]:
        """Return default configuration."""
        return {
            "version": 3,
            "llm_provider": LLMProvider.OLLAMA.value,
            "llm_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            "llm_api_key": "",
            "embed_model": os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:8b"),
            "llm_model": os.getenv("OLLAMA_LLM_MODEL", "qwen2.5:7b"),
            "top_k": int(os.getenv("RAG_TOP_K", "5")),
            "hybrid_search_enabled": True,
            "chunk_selection_enabled": False,
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
    def llm_provider(self) -> LLMProvider:
        val = self._data.get("llm_provider", LLMProvider.OLLAMA.value)
        try:
            return LLMProvider(val)
        except ValueError:
            return LLMProvider.OLLAMA

    @property
    def llm_base_url(self) -> str:
        return str(self._data.get("llm_base_url", "http://localhost:11434"))

    @property
    def llm_api_key(self) -> str:
        return str(self._data.get("llm_api_key", ""))

    @property
    def embed_model(self) -> str:
        return str(self._data.get("embed_model", "qwen3-embedding:8b"))

    @property
    def llm_model(self) -> str:
        return str(self._data.get("llm_model", "qwen2.5:7b"))

    @property
    def top_k(self) -> int:
        return int(self._data.get("top_k", 5))

    @property
    def hybrid_search_enabled(self) -> bool:
        return bool(self._data.get("hybrid_search_enabled", True))

    @property
    def chunk_selection_enabled(self) -> bool:
        return bool(self._data.get("chunk_selection_enabled", False))

    # -- Setters --

    def set_llm_provider(self, value: LLMProvider) -> None:
        self._data["llm_provider"] = value.value

    def set_llm_base_url(self, value: str) -> None:
        self._data["llm_base_url"] = value.strip()

    def set_llm_api_key(self, value: str) -> None:
        self._data["llm_api_key"] = value.strip()

    def set_embed_model(self, value: str) -> None:
        self._data["embed_model"] = value.strip()

    def set_llm_model(self, value: str) -> None:
        self._data["llm_model"] = value.strip()

    def set_top_k(self, value: int) -> None:
        self._data["top_k"] = max(1, int(value))

    def set_hybrid_search_enabled(self, value: bool) -> None:
        self._data["hybrid_search_enabled"] = bool(value)

    def set_chunk_selection_enabled(self, value: bool) -> None:
        self._data["chunk_selection_enabled"] = bool(value)
