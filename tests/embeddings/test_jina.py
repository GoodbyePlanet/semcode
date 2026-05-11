from __future__ import annotations

import httpx
import pytest
import respx

from server.config import settings
from server.embeddings.jina import JinaEmbeddingProvider


@pytest.fixture
def jina_settings(monkeypatch):
    monkeypatch.setattr(settings, "jina_url", "http://tei-test:80")
    monkeypatch.setattr(settings, "jina_dimensions", 768)


@pytest.fixture
async def provider(jina_settings):
    p = JinaEmbeddingProvider()
    yield p
    await p.close()


@respx.mock
async def test_embed_batch_posts_to_embed_endpoint(provider):
    route = respx.post("http://tei-test:80/embed").mock(
        return_value=httpx.Response(200, json=[[0.1] * 768, [0.2] * 768])
    )
    vectors = await provider.embed_batch(["hello", "world"])

    assert route.called
    body = route.calls.last.request.read()
    import json

    assert json.loads(body) == {"inputs": ["hello", "world"]}
    assert len(vectors) == 2
    assert len(vectors[0]) == 768


@respx.mock
async def test_embed_batch_chunks_at_32(provider):
    route = respx.post("http://tei-test:80/embed").mock(
        side_effect=lambda req: httpx.Response(
            200,
            json=[[0.0] * 768] * len(__import__("json").loads(req.read())["inputs"]),
        )
    )
    vectors = await provider.embed_batch([f"text-{i}" for i in range(70)])

    # 70 inputs / batch size 32 = 3 calls (32, 32, 6)
    assert route.call_count == 3
    assert len(vectors) == 70


@respx.mock
async def test_embed_batch_supports_openai_style_response(provider):
    respx.post("http://tei-test:80/embed").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.5] * 768}]})
    )
    vectors = await provider.embed_batch(["hello"])
    assert vectors == [[0.5] * 768]


@respx.mock
async def test_embed_query_returns_single_vector(provider):
    respx.post("http://tei-test:80/embed").mock(
        return_value=httpx.Response(200, json=[[0.3] * 768])
    )
    vec = await provider.embed_query("query")
    assert len(vec) == 768
    assert vec[0] == 0.3


async def test_embed_batch_empty_returns_empty(provider):
    assert await provider.embed_batch([]) == []


def test_dimensions_reads_from_settings(jina_settings, monkeypatch):
    monkeypatch.setattr(settings, "jina_dimensions", 1024)
    p = JinaEmbeddingProvider()
    assert p.dimensions == 1024
