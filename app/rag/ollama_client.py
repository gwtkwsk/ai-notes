from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Generator

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, base_url: str, embed_model: str, llm_model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._embed_model = embed_model
        self._llm_model = llm_model

    def embed(self, text: str) -> list[float]:
        import math

        logger.debug(
            f"Embedding text (length={len(text)} chars, first 50: '{text[:50]}...')"
        )
        payload = {"model": self._embed_model, "prompt": text}
        try:
            data = self._post_json("/api/embeddings", payload)
            embedding = data.get("embedding")
            if not isinstance(embedding, list) or not embedding:
                logger.warning(
                    f"Invalid embedding response for text: {text[:50]}..., "
                    f"got: {type(embedding)}"
                )
                return []

            # Validate all values are finite floats
            for i, val in enumerate(embedding):
                if not isinstance(val, (int, float)):
                    logger.error(
                        f"Invalid value type at index {i}: {type(val)} = {val}"
                    )
                    return []
                if math.isnan(val) or math.isinf(val):
                    logger.error(f"Invalid value at index {i}: {val} (NaN or Inf)")
                    return []

            logger.debug(
                f"Successfully generated embedding (dimension={len(embedding)})"
            )
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return []

    def generate(self, prompt: str, system: str | None = None) -> str:
        payload = {
            "model": self._llm_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 2048,
            },
        }
        if system:
            payload["system"] = system
        data = self._post_json("/api/generate", payload)
        return data.get("response", "")

    def generate_stream(
        self, prompt: str, system: str | None = None
    ) -> Generator[str, None, None]:
        payload = {
            "model": self._llm_model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": 0.7,
                "num_predict": 2048,
            },
        }
        if system:
            payload["system"] = system
        url = f"{self._base_url}/api/generate"
        body = json.dumps(payload).encode("utf-8")
        logger.info(f"Starting stream generation with model: {self._llm_model}")
        logger.debug(f"Prompt: {prompt[:200]}...")  # Log first 200 chars of prompt

        full_response = []  # Collect full response for logging
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            while True:
                line = response.readline()
                if not line:
                    break
                raw = line.decode("utf-8").strip()
                if not raw:
                    continue
                data = json.loads(raw)
                if data.get("error"):
                    logger.error(f"Ollama error: {data['error']}")
                    raise RuntimeError(data["error"])
                chunk = data.get("response", "")
                if chunk:
                    full_response.append(chunk)
                    yield chunk
                if data.get("done") is True:
                    break

        complete_response = "".join(full_response)
        logger.info(
            f"Stream generation complete. Total length: {len(complete_response)} chars"
        )
        logger.info(f"Full model response:\n{complete_response}")

    def check_connection(self) -> tuple[bool, str]:
        """Check if Ollama server is accessible.

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            url = f"{self._base_url}/api/tags"
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status == 200:
                    return True, "Connected successfully"
                return False, f"Server returned status {response.status}"
        except urllib.error.URLError as e:
            return False, f"Connection failed: {e.reason}"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def _post_json(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw)
