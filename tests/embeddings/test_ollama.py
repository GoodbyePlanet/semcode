from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from server.config import settings
from server.embeddings.ollama import OllamaEmbeddingProvider


@pytest.fixture
def ollama_settings(monkeypatch):
    monkeypatch.setattr(settings, "ollama_url", "http://ollama-test:11434")
    monkeypatch.setattr(settings, "ollama_model", "nomic-embed-text")
    monkeypatch.setattr(settings, "ollama_dimensions", None)


@pytest.fixture
async def provider(ollama_settings):
    p = OllamaEmbeddingProvider()
    yield p
    await p.close()


def _vectors_response(inputs: list[str], dim: int = 768) -> dict:
    return {"embeddings": [[0.0] * dim for _ in inputs]}


def test_unknown_model_without_dimensions_raises(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_url", "http://ollama-test:11434")
    monkeypatch.setattr(settings, "ollama_model", "totally-custom-embed")
    monkeypatch.setattr(settings, "ollama_dimensions", None)
    with pytest.raises(RuntimeError, match="OLLAMA_DIMENSIONS"):
        OllamaEmbeddingProvider()


def test_dimensions_native(ollama_settings) -> None:
    p = OllamaEmbeddingProvider()
    assert p.dimensions == 768


def test_dimensions_override(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_url", "http://ollama-test:11434")
    monkeypatch.setattr(settings, "ollama_model", "custom-embed")
    monkeypatch.setattr(settings, "ollama_dimensions", 512)
    p = OllamaEmbeddingProvider()
    assert p.dimensions == 512


@respx.mock
async def test_embed_batch_request_shape(provider) -> None:
    route = respx.post("http://ollama-test:11434/api/embed").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a", "b"]))
    )
    await provider.embed_batch(["a", "b"])
    body = json.loads(route.calls.last.request.read())
    assert body == {"model": "nomic-embed-text", "input": ["a", "b"]}


@respx.mock
async def test_embed_batch_chunks_at_32(provider) -> None:
    route = respx.post("http://ollama-test:11434/api/embed").mock(
        side_effect=lambda req: httpx.Response(
            200,
            json=_vectors_response(json.loads(req.read())["input"]),
        )
    )
    inputs = [f"x-{i}" for i in range(70)]
    vectors = await provider.embed_batch(inputs)
    # 70 / 32 = 3 calls (32, 32, 6)
    assert route.call_count == 3
    assert len(vectors) == 70


@respx.mock
async def test_embed_query_returns_single_vector(provider) -> None:
    respx.post("http://ollama-test:11434/api/embed").mock(
        return_value=httpx.Response(200, json=_vectors_response(["q"]))
    )
    vec = await provider.embed_query("q")
    assert len(vec) == 768


async def test_embed_batch_empty(provider) -> None:
    assert await provider.embed_batch([]) == []


@respx.mock
async def test_transient_server_error_is_retried(provider, monkeypatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    respx.post("http://ollama-test:11434/api/embed").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json=_vectors_response(["a"])),
        ]
    )
    vectors = await provider.embed_batch(["a"])
    assert len(vectors) == 1
    assert sleep_calls == [10]


@respx.mock
async def test_connection_error_is_retried(provider, monkeypatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    respx.post("http://ollama-test:11434/api/embed").mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.Response(200, json=_vectors_response(["a"])),
        ]
    )
    vectors = await provider.embed_batch(["a"])
    assert len(vectors) == 1
    assert sleep_calls == [10]


@respx.mock
async def test_server_error_exhausted_raises(provider, monkeypatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    respx.post("http://ollama-test:11434/api/embed").mock(
        return_value=httpx.Response(500)
    )
    with pytest.raises(httpx.HTTPStatusError):
        await provider.embed_batch(["a"])
    assert sleep_calls == [10, 20, 30, 40]


@respx.mock
async def test_response_length_mismatch_raises(provider) -> None:
    respx.post("http://ollama-test:11434/api/embed").mock(
        return_value=httpx.Response(200, json=_vectors_response(["only-one"]))
    )
    with pytest.raises(ValueError, match="2 inputs"):
        await provider.embed_batch(["a", "b"])
