from __future__ import annotations

import json

import httpx
import pytest
import respx

from server.config import settings
from server.embeddings.voyage import VoyageEmbeddingProvider


@pytest.fixture
def voyage_settings(monkeypatch):
    monkeypatch.setattr(settings, "voyage_api_key", "test-key")
    monkeypatch.setattr(settings, "voyage_model", "voyage-code-3")
    monkeypatch.setattr(settings, "voyage_dimensions", None)


@pytest.fixture
async def provider(voyage_settings):
    p = VoyageEmbeddingProvider()
    yield p
    await p.close()


def _vectors_response(inputs: list[str], dim: int = 1024) -> dict:
    return {"data": [{"embedding": [0.1] * dim} for _ in inputs]}


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "voyage_api_key", "")
    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY"):
        VoyageEmbeddingProvider()


def test_unknown_model_without_dimensions_raises(monkeypatch):
    monkeypatch.setattr(settings, "voyage_api_key", "k")
    monkeypatch.setattr(settings, "voyage_model", "voyage-future-99")
    monkeypatch.setattr(settings, "voyage_dimensions", None)
    with pytest.raises(RuntimeError, match="VOYAGE_DIMENSIONS"):
        VoyageEmbeddingProvider()


def test_dimensions_native(voyage_settings):
    p = VoyageEmbeddingProvider()
    assert p.dimensions == 1024  # voyage-code-3 native


def test_dimensions_override(monkeypatch):
    monkeypatch.setattr(settings, "voyage_api_key", "k")
    monkeypatch.setattr(settings, "voyage_model", "voyage-code-3")
    monkeypatch.setattr(settings, "voyage_dimensions", 256)
    p = VoyageEmbeddingProvider()
    assert p.dimensions == 256


@respx.mock
async def test_embed_batch_uses_document_input_type(provider):
    route = respx.post("https://api.voyageai.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a", "b"]))
    )
    await provider.embed_batch(["a", "b"])
    body = json.loads(route.calls.last.request.read())
    assert body["model"] == "voyage-code-3"
    assert body["input"] == ["a", "b"]
    assert body["input_type"] == "document"
    assert "output_dimension" not in body


@respx.mock
async def test_embed_query_uses_query_input_type(provider):
    route = respx.post("https://api.voyageai.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["q"]))
    )
    await provider.embed_query("q")
    body = json.loads(route.calls.last.request.read())
    assert body["input_type"] == "query"
    assert body["input"] == ["q"]


@respx.mock
async def test_embed_batch_chunks_at_128(provider):
    route = respx.post("https://api.voyageai.com/v1/embeddings").mock(
        side_effect=lambda req: httpx.Response(
            200,
            json=_vectors_response(json.loads(req.read())["input"]),
        )
    )
    inputs = [f"text-{i}" for i in range(300)]
    vectors = await provider.embed_batch(inputs)
    # 300 / 128 = 3 calls (128, 128, 44)
    assert route.call_count == 3
    assert len(vectors) == 300


@respx.mock
async def test_authorization_header_set(provider):
    route = respx.post("https://api.voyageai.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a"]))
    )
    await provider.embed_batch(["a"])
    auth = route.calls.last.request.headers.get("authorization")
    assert auth == "Bearer test-key"


@respx.mock
async def test_embed_batch_passes_output_dimension_when_overridden(monkeypatch):
    monkeypatch.setattr(settings, "voyage_api_key", "test-key")
    monkeypatch.setattr(settings, "voyage_model", "voyage-code-3")
    monkeypatch.setattr(settings, "voyage_dimensions", 512)

    route = respx.post("https://api.voyageai.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a"], dim=512))
    )
    p = VoyageEmbeddingProvider()
    try:
        await p.embed_batch(["a"])
    finally:
        await p.close()
    body = json.loads(route.calls.last.request.read())
    assert body["output_dimension"] == 512


async def test_embed_batch_empty(provider):
    assert await provider.embed_batch([]) == []
