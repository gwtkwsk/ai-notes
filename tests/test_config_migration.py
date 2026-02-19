"""Tests for Config migration and v2 defaults."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Config, LLMProvider


def test_migration_v1_to_v2(tmp_path: Path) -> None:
    """Config loaded from a v1 file should be migrated to v2."""
    config_file = tmp_path / "config.json"
    v1_data = {
        "version": 1,
        "ollama_base_url": "http://ollama.local:12000",
        "embed_model": "some-embed",
        "llm_model": "some-llm",
        "top_k": 3,
    }
    config_file.write_text(json.dumps(v1_data), encoding="utf-8")

    config = Config(config_path=config_file)

    assert config.llm_provider == LLMProvider.OLLAMA
    assert config.llm_base_url == "http://ollama.local:12000"
    assert config.llm_api_key == ""
    assert config.embed_model == "some-embed"
    assert config.llm_model == "some-llm"
    assert config.top_k == 3


def test_defaults_v2(tmp_path: Path) -> None:
    """New Config on a nonexistent path should have correct v2 defaults."""
    config_file = tmp_path / "nonexistent" / "config.json"
    config = Config(config_path=config_file)

    assert config.llm_provider == LLMProvider.OLLAMA
    assert config.llm_base_url == "http://localhost:11434"
    assert config.llm_api_key == ""
    assert config.embed_model != ""
    assert config.llm_model != ""
    assert config.top_k >= 1


def test_set_and_save_llm_provider(tmp_path: Path) -> None:
    """Setting provider, saving and reloading should persist the value."""
    config_file = tmp_path / "config.json"
    config = Config(config_path=config_file)

    config.set_llm_provider(LLMProvider.OPENAI_COMPATIBLE)
    config.set_llm_base_url("http://openai.example.com")
    config.set_llm_api_key("sk-secret")
    config.save()

    config2 = Config(config_path=config_file)
    assert config2.llm_provider == LLMProvider.OPENAI_COMPATIBLE
    assert config2.llm_base_url == "http://openai.example.com"
    assert config2.llm_api_key == "sk-secret"
