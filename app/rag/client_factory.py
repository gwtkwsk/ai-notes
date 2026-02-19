from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import LLMProvider
from app.rag.llm_client import LLMClient

if TYPE_CHECKING:
    from app.config import Config


def create_llm_client(config: Config) -> LLMClient:
    """Instantiate the correct LLM client based on the configured provider."""
    if config.llm_provider == LLMProvider.OPENAI_COMPATIBLE:
        from app.rag.openai_client import OpenAICompatibleClient

        return OpenAICompatibleClient(
            base_url=config.llm_base_url,
            embed_model=config.embed_model,
            llm_model=config.llm_model,
            api_key=config.llm_api_key,
        )
    from app.rag.ollama_client import OllamaClient

    return OllamaClient(
        base_url=config.llm_base_url,
        embed_model=config.embed_model,
        llm_model=config.llm_model,
    )
