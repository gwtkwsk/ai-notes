from __future__ import annotations

import json
import urllib.request
from typing import Generator, List


class OllamaClient:
    def __init__(self, base_url: str, embed_model: str, llm_model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._embed_model = embed_model
        self._llm_model = llm_model

    def embed(self, text: str) -> List[float]:
        payload = {"model": self._embed_model, "prompt": text}
        data = self._post_json("/api/embeddings", payload)
        return data.get("embedding", [])

    def generate(self, prompt: str) -> str:
        payload = {"model": self._llm_model, "prompt": prompt, "stream": False}
        data = self._post_json("/api/generate", payload)
        return data.get("response", "")

    def generate_stream(self, prompt: str) -> Generator[str, None, None]:
        payload = {"model": self._llm_model, "prompt": prompt, "stream": True}
        url = f"{self._base_url}/api/generate"
        body = json.dumps(payload).encode("utf-8")
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
                    raise RuntimeError(data["error"])
                chunk = data.get("response", "")
                if chunk:
                    yield chunk
                if data.get("done") is True:
                    break

    def _post_json(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw)
