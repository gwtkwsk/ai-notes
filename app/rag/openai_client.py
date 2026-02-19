from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Generator

logger = logging.getLogger(__name__)


class OpenAICompatibleClient:
    """HTTP client for any OpenAI-compatible LLM API endpoint.

    Works with: OpenAI, LM Studio (local), any custom OpenAI-compatible server.
    """

    def __init__(
        self,
        base_url: str,
        embed_model: str,
        llm_model: str,
        api_key: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._embed_model = embed_model
        self._llm_model = llm_model
        self._api_key = api_key

    def _make_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _post_json(self, path: str, payload: dict) -> dict:  # type: ignore[type-arg]
        url = f"{self._base_url}{path}"
        data = json.dumps(payload).encode()
        headers = self._make_headers()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]

    def _get_json(self, path: str) -> dict:  # type: ignore[type-arg]
        url = f"{self._base_url}{path}"
        headers = self._make_headers()
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]

    def embed(self, text: str) -> list[float]:
        try:
            payload = {"model": self._embed_model, "input": text}
            response = self._post_json("/v1/embeddings", payload)
            return list(response["data"][0]["embedding"])
        except Exception:
            logger.exception("Embedding request failed")
            return []

    def _build_messages(self, prompt: str, system: str | None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def generate(self, prompt: str, system: str | None = None) -> str:
        try:
            payload = {
                "model": self._llm_model,
                "messages": self._build_messages(prompt, system),
                "stream": False,
                "temperature": 0.7,
                "max_tokens": 2048,
            }
            response = self._post_json("/v1/chat/completions", payload)
            return str(response["choices"][0]["message"]["content"])
        except Exception:
            logger.exception("Generate request failed")
            return ""

    def generate_stream(
        self, prompt: str, system: str | None = None
    ) -> Generator[str, None, None]:
        url = f"{self._base_url}/v1/chat/completions"
        payload = {
            "model": self._llm_model,
            "messages": self._build_messages(prompt, system),
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 2048,
        }
        data = json.dumps(payload).encode()
        headers = self._make_headers()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        parsed = json.loads(chunk)
                        content = parsed["choices"][0]["delta"].get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except Exception:
            logger.exception("Streaming generate request failed")

    def check_connection(self) -> tuple[bool, str]:
        try:
            self._get_json("/v1/models")
            return True, "Connected successfully"
        except urllib.error.HTTPError as e:
            return False, f"HTTP error: {e.code} {e.reason}"
        except urllib.error.URLError as e:
            return False, f"Connection error: {e.reason}"
        except Exception as e:
            return False, f"Unexpected error: {e}"
