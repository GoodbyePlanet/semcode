from __future__ import annotations

import json

import httpx
import pytest
import respx

from server.config import settings
from server.embeddings.openai import OpenAIEmbeddingProvider


@pytest.fixture
def openai_settings(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_embedding_model", "text-embedding-3-large")
    monkeypatch.setattr(settings, "openai_dimensions", None)


@pytest.fixture
async def provider(openai_settings):
    p = OpenAIEmbeddingProvider()
    yield p
    await p.close()


def _vectors_response(inputs: list[str], dim: int = 3072) -> dict:
    return {"data": [{"embedding": [0.0] * dim} for _ in inputs]}


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIEmbeddingProvider()


def test_unknown_model_without_dimensions_raises(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "k")
    monkeypatch.setattr(settings, "openai_embedding_model", "text-future-99")
    monkeypatch.setattr(settings, "openai_dimensions", None)
    with pytest.raises(RuntimeError, match="OPENAI_DIMENSIONS"):
        OpenAIEmbeddingProvider()


def test_dimensions_native(openai_settings):
    p = OpenAIEmbeddingProvider()
    assert p.dimensions == 3072  # text-embedding-3-large native


def test_dimensions_override(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "k")
    monkeypatch.setattr(settings, "openai_embedding_model", "text-embedding-3-large")
    monkeypatch.setattr(settings, "openai_dimensions", 1024)
    p = OpenAIEmbeddingProvider()
    assert p.dimensions == 1024


@respx.mock
async def test_embed_batch_request_shape(provider):
    route = respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a", "b"]))
    )
    await provider.embed_batch(["a", "b"])
    body = json.loads(route.calls.last.request.read())
    assert body == {"model": "text-embedding-3-large", "input": ["a", "b"]}


@respx.mock
async def test_embed_batch_includes_dimensions_when_overridden(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_embedding_model", "text-embedding-3-large")
    monkeypatch.setattr(settings, "openai_dimensions", 512)

    route = respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a"], dim=512))
    )
    p = OpenAIEmbeddingProvider()
    try:
        await p.embed_batch(["a"])
    finally:
        await p.close()
    body = json.loads(route.calls.last.request.read())
    assert body["dimensions"] == 512


@respx.mock
async def test_embed_batch_chunks_at_128(provider):
    route = respx.post("https://api.openai.com/v1/embeddings").mock(
        side_effect=lambda req: httpx.Response(
            200,
            json=_vectors_response(json.loads(req.read())["input"]),
        )
    )
    inputs = [f"x-{i}" for i in range(257)]
    vectors = await provider.embed_batch(inputs)
    # 257 / 128 = 3 calls (128, 128, 1)
    assert route.call_count == 3
    assert len(vectors) == 257


@respx.mock
async def test_authorization_header_set(provider):
    route = respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a"]))
    )
    await provider.embed_batch(["a"])
    assert route.calls.last.request.headers.get("authorization") == "Bearer sk-test"


@respx.mock
async def test_embed_query_returns_single_vector(provider):
    respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["q"]))
    )
    vec = await provider.embed_query("q")
    assert len(vec) == 3072


async def test_embed_batch_empty(provider):
    assert await provider.embed_batch([]) == []
