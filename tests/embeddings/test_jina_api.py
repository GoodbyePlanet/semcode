from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from server.config import settings
from server.embeddings.jina_api import JinaApiEmbeddingProvider


@pytest.fixture
def jina_api_settings(monkeypatch):
    monkeypatch.setattr(settings, "jina_api_key", "test-key")
    monkeypatch.setattr(settings, "jina_api_model", "jina-embeddings-v2-base-code")
    monkeypatch.setattr(settings, "jina_api_dimensions", None)


@pytest.fixture
async def provider(jina_api_settings):
    p = JinaApiEmbeddingProvider()
    yield p
    await p.close()


def _vectors_response(inputs: list[str], dim: int = 768) -> dict:
    return {"data": [{"embedding": [0.1] * dim} for _ in inputs]}


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "jina_api_key", "")
    with pytest.raises(RuntimeError, match="JINA_API_KEY"):
        JinaApiEmbeddingProvider()


def test_unknown_model_without_dimensions_raises(monkeypatch):
    monkeypatch.setattr(settings, "jina_api_key", "k")
    monkeypatch.setattr(settings, "jina_api_model", "jina-future-99")
    monkeypatch.setattr(settings, "jina_api_dimensions", None)
    with pytest.raises(RuntimeError, match="JINA_API_DIMENSIONS"):
        JinaApiEmbeddingProvider()


def test_dimensions_native(jina_api_settings):
    p = JinaApiEmbeddingProvider()
    assert p.dimensions == 768  # jina-embeddings-v2-base-code native


def test_dimensions_override(monkeypatch):
    monkeypatch.setattr(settings, "jina_api_key", "k")
    monkeypatch.setattr(settings, "jina_api_model", "jina-code-embeddings-1.5b")
    monkeypatch.setattr(settings, "jina_api_dimensions", 512)
    p = JinaApiEmbeddingProvider()
    assert p.dimensions == 512


@respx.mock
async def test_embed_batch_omits_task_for_v2_model(provider):
    route = respx.post("https://api.jina.ai/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a", "b"]))
    )
    await provider.embed_batch(["a", "b"])
    body = json.loads(route.calls.last.request.read())
    assert body["model"] == "jina-embeddings-v2-base-code"
    assert body["input"] == ["a", "b"]
    assert body["truncate"] is True  # server-side truncation on token boundary
    assert "task" not in body  # v2 models don't accept the task parameter
    assert "dimensions" not in body


@respx.mock
async def test_embed_query_omits_task_for_v2_model(provider):
    route = respx.post("https://api.jina.ai/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["q"]))
    )
    await provider.embed_query("q")
    body = json.loads(route.calls.last.request.read())
    assert "task" not in body
    assert body["input"] == ["q"]


@respx.mock
async def test_embed_batch_sends_task_for_code_embeddings_model(monkeypatch):
    monkeypatch.setattr(settings, "jina_api_key", "test-key")
    monkeypatch.setattr(settings, "jina_api_model", "jina-code-embeddings-1.5b")
    monkeypatch.setattr(settings, "jina_api_dimensions", None)
    route = respx.post("https://api.jina.ai/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a"], dim=1536))
    )
    p = JinaApiEmbeddingProvider()
    try:
        await p.embed_batch(["a"])
    finally:
        await p.close()
    body = json.loads(route.calls.last.request.read())
    assert body["task"] == "nl2code.passage"


@respx.mock
async def test_embed_query_sends_task_for_code_embeddings_model(monkeypatch):
    monkeypatch.setattr(settings, "jina_api_key", "test-key")
    monkeypatch.setattr(settings, "jina_api_model", "jina-code-embeddings-1.5b")
    monkeypatch.setattr(settings, "jina_api_dimensions", None)
    route = respx.post("https://api.jina.ai/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["q"], dim=1536))
    )
    p = JinaApiEmbeddingProvider()
    try:
        await p.embed_query("q")
    finally:
        await p.close()
    body = json.loads(route.calls.last.request.read())
    assert body["task"] == "nl2code.query"


@respx.mock
async def test_embed_batch_chunks_at_128(provider):
    route = respx.post("https://api.jina.ai/v1/embeddings").mock(
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
    route = respx.post("https://api.jina.ai/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a"]))
    )
    await provider.embed_batch(["a"])
    auth = route.calls.last.request.headers.get("authorization")
    assert auth == "Bearer test-key"


@respx.mock
async def test_embed_batch_passes_dimensions_when_overridden(monkeypatch):
    monkeypatch.setattr(settings, "jina_api_key", "test-key")
    monkeypatch.setattr(settings, "jina_api_model", "jina-code-embeddings-1.5b")
    monkeypatch.setattr(settings, "jina_api_dimensions", 256)

    route = respx.post("https://api.jina.ai/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["a"], dim=256))
    )
    p = JinaApiEmbeddingProvider()
    try:
        await p.embed_batch(["a"])
    finally:
        await p.close()
    body = json.loads(route.calls.last.request.read())
    assert body["dimensions"] == 256


async def test_embed_batch_empty(provider):
    assert await provider.embed_batch([]) == []


async def test_embed_batch_raises_on_empty_string(provider):
    with pytest.raises(ValueError, match="empty/whitespace"):
        await provider.embed_batch([""])


async def test_embed_batch_raises_on_whitespace_only(provider):
    with pytest.raises(ValueError, match="empty/whitespace"):
        await provider.embed_batch(["   \n\t  "])


@respx.mock
async def test_rate_limit_backoff_delays(provider, monkeypatch):
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    respx.post("https://api.jina.ai/v1/embeddings").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(200, json=_vectors_response(["a"])),
        ]
    )
    await provider.embed_batch(["a"])
    assert sleep_calls == [10, 20, 30]


@respx.mock
async def test_rate_limit_honors_retry_after_header(provider, monkeypatch):
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    respx.post("https://api.jina.ai/v1/embeddings").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json=_vectors_response(["a"])),
        ]
    )
    await provider.embed_batch(["a"])
    assert sleep_calls == [7]


@respx.mock
async def test_rate_limit_all_retries_exhausted_raises(provider, monkeypatch):
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    respx.post("https://api.jina.ai/v1/embeddings").mock(
        return_value=httpx.Response(429)
    )
    with pytest.raises(httpx.HTTPStatusError):
        await provider.embed_batch(["a"])
    assert sleep_calls == [10, 20, 30, 40]


@respx.mock
async def test_response_length_mismatch_raises(provider):
    # Server returns fewer vectors than inputs — should raise ValueError
    respx.post("https://api.jina.ai/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_vectors_response(["only-one"]))
    )
    with pytest.raises(ValueError, match="2 inputs"):
        await provider.embed_batch(["a", "b"])
