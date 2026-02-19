"""Tests for OpenAICompatibleClient using mocked urllib."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from app.rag.openai_client import OpenAICompatibleClient


def _mock_response(data: dict) -> MagicMock:
    body = json.dumps(data).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _mock_stream_response(lines: list[str]) -> MagicMock:
    encoded = [line.encode("utf-8") + b"\n" for line in lines]
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.__iter__ = lambda s: iter(encoded)
    return mock_resp


class TestEmbed:
    def test_embed_success(self) -> None:
        client = OpenAICompatibleClient("http://localhost:1234", "emb-model", "llm")
        response_data = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        with patch(
            "urllib.request.urlopen", return_value=_mock_response(response_data)
        ):
            result = client.embed("hello world")
        assert result == [0.1, 0.2, 0.3]

    def test_embed_failure_returns_empty(self) -> None:
        client = OpenAICompatibleClient("http://localhost:1234", "emb-model", "llm")
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("refused"),
        ):
            result = client.embed("hello")
        assert result == []


class TestGenerate:
    def test_generate_success(self) -> None:
        client = OpenAICompatibleClient("http://localhost:1234", "emb", "llm-model")
        response_data = {"choices": [{"message": {"content": "Paris"}}]}
        with patch(
            "urllib.request.urlopen", return_value=_mock_response(response_data)
        ):
            result = client.generate("What is the capital of France?")
        assert result == "Paris"

    def test_generate_failure_returns_empty(self) -> None:
        client = OpenAICompatibleClient("http://localhost:1234", "emb", "llm-model")
        with patch(
            "urllib.request.urlopen",
            side_effect=Exception("network error"),
        ):
            result = client.generate("question")
        assert result == ""


class TestCheckConnection:
    def test_check_connection_success(self) -> None:
        client = OpenAICompatibleClient("http://localhost:1234", "emb", "llm")
        models_data = {"data": [{"id": "gpt-4"}]}
        with patch("urllib.request.urlopen", return_value=_mock_response(models_data)):
            success, message = client.check_connection()
        assert success is True
        assert "Connected" in message

    def test_check_connection_url_error(self) -> None:
        client = OpenAICompatibleClient("http://localhost:1234", "emb", "llm")
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            success, message = client.check_connection()
        assert success is False
        assert "Connection error" in message


class TestApiKey:
    def test_api_key_header_included(self) -> None:
        client = OpenAICompatibleClient(
            "http://localhost:1234", "emb", "llm", api_key="sk-test"
        )
        captured: list[urllib.request.Request] = []

        def fake_urlopen(req: urllib.request.Request, timeout: int = 0) -> MagicMock:
            captured.append(req)
            return _mock_response({"data": []})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.check_connection()

        assert len(captured) == 1
        assert captured[0].get_header("Authorization") == "Bearer sk-test"

    def test_api_key_header_omitted(self) -> None:
        client = OpenAICompatibleClient(
            "http://localhost:1234", "emb", "llm", api_key=""
        )
        captured: list[urllib.request.Request] = []

        def fake_urlopen(req: urllib.request.Request, timeout: int = 0) -> MagicMock:
            captured.append(req)
            return _mock_response({"data": []})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.check_connection()

        assert len(captured) == 1
        assert captured[0].get_header("Authorization") is None
