from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from server.embeddings.http_batch import embed_in_batches, post_with_retry

_URL = "https://example.test/embed"


@pytest.fixture
async def client():
    c = httpx.AsyncClient()
    yield c
    await c.aclose()


@pytest.fixture
def sleep_calls(monkeypatch) -> list[float]:
    calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return calls


def _vectors(n: int, dim: int = 3) -> dict:
    return {"data": [{"embedding": [0.1] * dim} for _ in range(n)]}


def _extract(data) -> list[list[float]]:
    return [item["embedding"] for item in data.get("data", [])]


@respx.mock
async def test_no_retry_on_success(client, sleep_calls) -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_vectors(1)))
    resp = await post_with_retry(client, _URL, {}, provider="Test")
    assert resp.status_code == 200
    assert sleep_calls == []


@respx.mock
async def test_rate_limit_backoff_delays(client, sleep_calls) -> None:
    respx.post(_URL).mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(200, json=_vectors(1)),
        ]
    )
    await post_with_retry(client, _URL, {}, provider="Test")
    assert sleep_calls == [10, 20, 30]


@respx.mock
async def test_rate_limit_honors_retry_after_header(client, sleep_calls) -> None:
    respx.post(_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json=_vectors(1)),
        ]
    )
    await post_with_retry(client, _URL, {}, provider="Test")
    assert sleep_calls == [7]


@respx.mock
async def test_rate_limit_exhausted_raises(client, sleep_calls) -> None:
    respx.post(_URL).mock(return_value=httpx.Response(429))
    with pytest.raises(httpx.HTTPStatusError):
        await post_with_retry(client, _URL, {}, provider="Test")
    assert sleep_calls == [10, 20, 30, 40]


@respx.mock
async def test_server_error_is_retried(client, sleep_calls) -> None:
    respx.post(_URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json=_vectors(1)),
        ]
    )
    resp = await post_with_retry(client, _URL, {}, provider="Test")
    assert resp.status_code == 200
    assert sleep_calls == [10]


@respx.mock
async def test_server_error_exhausted_raises(client, sleep_calls) -> None:
    respx.post(_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await post_with_retry(client, _URL, {}, provider="Test")
    assert sleep_calls == [10, 20, 30, 40]


@respx.mock
async def test_transport_error_is_retried(client, sleep_calls) -> None:
    respx.post(_URL).mock(
        side_effect=[
            httpx.ConnectError("connection reset"),
            httpx.Response(200, json=_vectors(1)),
        ]
    )
    resp = await post_with_retry(client, _URL, {}, provider="Test")
    assert resp.status_code == 200
    assert sleep_calls == [10]


@respx.mock
async def test_transport_error_exhausted_raises(client, sleep_calls) -> None:
    respx.post(_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))
    with pytest.raises(httpx.TransportError):
        await post_with_retry(client, _URL, {}, provider="Test")
    # The last attempt re-raises instead of sleeping on the way out.
    assert sleep_calls == [10, 20, 30]


@respx.mock
async def test_client_error_is_not_retried(client, sleep_calls) -> None:
    respx.post(_URL).mock(return_value=httpx.Response(400, text="bad request"))
    with pytest.raises(httpx.HTTPStatusError):
        await post_with_retry(client, _URL, {}, provider="Test")
    assert sleep_calls == []


@respx.mock
async def test_embed_in_batches_chunks_requests(client) -> None:
    route = respx.post(_URL).mock(
        side_effect=lambda request: httpx.Response(
            200, json=_vectors(len(request.read().decode().split("|")))
        )
    )
    vectors = await embed_in_batches(
        [f"t{i}" for i in range(5)],
        client=client,
        url=_URL,
        provider="Test",
        batch_size=2,
        make_body=lambda batch: {"input": "|".join(batch)},
        extract=_extract,
    )
    assert route.call_count == 3
    assert len(vectors) == 5


async def test_embed_in_batches_empty_makes_no_request(client) -> None:
    vectors = await embed_in_batches(
        [],
        client=client,
        url=_URL,
        provider="Test",
        batch_size=2,
        make_body=lambda batch: {},
        extract=_extract,
    )
    assert vectors == []


@respx.mock
async def test_embed_in_batches_length_mismatch_raises(client) -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_vectors(1)))
    with pytest.raises(ValueError, match="Test returned 1 vectors for 2 inputs"):
        await embed_in_batches(
            ["a", "b"],
            client=client,
            url=_URL,
            provider="Test",
            batch_size=128,
            make_body=lambda batch: {},
            extract=_extract,
        )
