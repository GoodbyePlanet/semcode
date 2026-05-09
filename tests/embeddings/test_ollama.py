from __future__ import annotations

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


def test_unknown_model_without_dimensions_raises(monkeypatch):
    monkeypatch.setattr(settings, "ollama_url", "http://ollama-test:11434")
    monkeypatch.setattr(settings, "ollama_model", "totally-custom-embed")
    monkeypatch.setattr(settings, "ollama_dimensions", None)
    with pytest.raises(RuntimeError, match="OLLAMA_DIMENSIONS"):
        OllamaEmbeddingProvider()


def test_dimensions_native(ollama_settings):
    p = OllamaEmbeddingProvider()
    assert p.dimensions == 768


def test_dimensions_override(monkeypatch):
    monkeypatch.setattr(settings, "ollama_url", "http://ollama-test:11434")
    monkeypatch.setattr(settings, "ollama_model", "custom-embed")
    monkeypatch.setattr(settings, "ollama_dimensions", 512)
    p = OllamaEmbeddingProvider()
    assert p.dimensions == 512


@respx.mock
async def test_embed_batch_request_shape(provider):
    route = respx.post("http://ollama-test:11434/api/embed").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a", "b"]))
    )
    await provider.embed_batch(["a", "b"])
    body = json.loads(route.calls.last.request.read())
    assert body == {"model": "nomic-embed-text", "input": ["a", "b"]}


@respx.mock
async def test_embed_batch_chunks_at_32(provider):
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
async def test_embed_query_returns_single_vector(provider):
    respx.post("http://ollama-test:11434/api/embed").mock(
        return_value=httpx.Response(200, json=_vectors_response(["q"]))
    )
    vec = await provider.embed_query("q")
    assert len(vec) == 768


async def test_embed_batch_empty(provider):
    assert await provider.embed_batch([]) == []
