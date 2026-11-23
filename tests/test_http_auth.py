from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from server.http_auth import BearerTokenMiddleware

TOKEN = "a" * 32


async def _ok(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


async def _stream(_: Request) -> StreamingResponse:
    async def lines() -> AsyncIterator[bytes]:
        for i in range(3):
            yield f'{{"n": {i}}}\n'.encode()

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Starlette(
        routes=[Route("/", _ok), Route("/stream", _stream, methods=["POST"])]
    )
    app.add_middleware(BearerTokenMiddleware, token=TOKEN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": f"Bearer {'b' * 32}"},
        {"Authorization": f"Bearer {TOKEN}x"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": TOKEN},
    ],
    ids=["missing", "wrong", "prefix", "basic", "no-credentials", "blank", "no-scheme"],
)
async def test_rejects_bad_credentials(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get("/", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"error": "unauthorized"}


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
async def test_accepts_correct_token(client: httpx.AsyncClient, scheme: str) -> None:
    response = await client.get("/", headers={"Authorization": f"{scheme} {TOKEN}"})

    assert response.status_code == 200
    assert response.text == "ok"


async def test_streams_pass_through(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/stream", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    assert response.text.splitlines() == ['{"n": 0}', '{"n": 1}', '{"n": 2}']


async def test_lifespan_passes_through_without_credentials() -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    async def receive() -> dict:
        return {"type": "lifespan.startup"}

    async def send(message: dict) -> None:
        raise AssertionError(f"middleware answered a lifespan scope: {message}")

    await BearerTokenMiddleware(inner, token=TOKEN)({"type": "lifespan"}, receive, send)

    assert seen == ["lifespan"]


def test_requires_non_empty_token() -> None:
    with pytest.raises(ValueError):
        BearerTokenMiddleware(Starlette(), token="")
