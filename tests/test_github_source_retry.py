from __future__ import annotations

import httpx
import pytest
import respx

import server.indexer.github_source as gh
from server.indexer.github_source import fetch_blob_content

_API = "https://api.github.com"
_REPO = "owner/repo"
_BLOB_URL = f"{_API}/repos/{_REPO}/git/blobs/deadbeef"


@pytest.fixture
def no_sleep(monkeypatch):
    """Record backoff waits instead of serving them."""
    waits: list[float] = []

    async def _sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(gh.asyncio, "sleep", _sleep)
    return waits


def _blob(content: str) -> httpx.Response:
    import base64

    encoded = base64.b64encode(content.encode()).decode()
    return httpx.Response(200, json={"content": encoded})


@respx.mock
async def test_transport_error_is_retried(no_sleep) -> None:
    route = respx.get(_BLOB_URL).mock(
        side_effect=[
            httpx.ConnectError("connection reset"),
            _blob("recovered"),
        ]
    )

    content = await fetch_blob_content("tok", _REPO, "deadbeef")

    assert content == b"recovered"
    assert route.call_count == 2
    assert no_sleep == [gh._GH_BACKOFF_DELAYS[0]]


@respx.mock
async def test_server_error_is_retried(no_sleep) -> None:
    route = respx.get(_BLOB_URL).mock(
        side_effect=[httpx.Response(502), _blob("recovered")]
    )

    content = await fetch_blob_content("tok", _REPO, "deadbeef")

    assert content == b"recovered"
    assert route.call_count == 2


@respx.mock
async def test_transport_error_raises_after_exhausting_attempts(no_sleep) -> None:
    route = respx.get(_BLOB_URL).mock(side_effect=httpx.ConnectError("down"))

    with pytest.raises(httpx.ConnectError):
        await fetch_blob_content("tok", _REPO, "deadbeef")

    assert route.call_count == gh._GH_ATTEMPTS


@respx.mock
async def test_server_error_raises_after_exhausting_attempts(no_sleep) -> None:
    route = respx.get(_BLOB_URL).mock(return_value=httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_blob_content("tok", _REPO, "deadbeef")

    assert route.call_count == gh._GH_ATTEMPTS


@respx.mock
async def test_rate_limit_waits_for_the_reset_window(no_sleep) -> None:
    route = respx.get(_BLOB_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "30"}),
            _blob("recovered"),
        ]
    )

    content = await fetch_blob_content("tok", _REPO, "deadbeef")

    assert content == b"recovered"
    assert route.call_count == 2
    # Rate limits honour the server's window, not the short 5xx backoff.
    assert no_sleep == [30.0]


@respx.mock
async def test_rate_limit_wait_is_capped(no_sleep) -> None:
    respx.get(_BLOB_URL).mock(
        side_effect=[
            httpx.Response(403, headers={"Retry-After": "9999"}),
            _blob("recovered"),
        ]
    )

    await fetch_blob_content("tok", _REPO, "deadbeef")

    assert no_sleep == [120.0]


@respx.mock
async def test_client_error_is_not_retried(no_sleep) -> None:
    route = respx.get(_BLOB_URL).mock(return_value=httpx.Response(404))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_blob_content("tok", _REPO, "deadbeef")

    assert route.call_count == 1
    assert no_sleep == []
