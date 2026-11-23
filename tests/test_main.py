from __future__ import annotations

import logging

import httpx
import pytest
from pydantic import SecretStr

from server import main as main_module
from server.config import settings
from server.http_auth import BearerTokenMiddleware


@pytest.fixture
def streamable_http(monkeypatch) -> None:
    monkeypatch.setattr(settings, "mcp_transport", "streamable-http")


def test_build_http_app_is_stateless_by_default(streamable_http) -> None:
    main_module.build_http_app()
    assert main_module.mcp.session_manager.stateless is True


def test_build_http_app_is_stateful_when_disabled(streamable_http, monkeypatch) -> None:
    monkeypatch.setattr(settings, "mcp_stateless_http", False)
    main_module.build_http_app()
    assert main_module.mcp.session_manager.stateless is False


def test_build_http_app_wraps_lifespan(streamable_http) -> None:
    app = main_module.build_http_app()
    assert app.router.lifespan_context.__name__ == "combined"


def test_build_http_app_sse_transport_ignores_stateless(monkeypatch) -> None:
    # `sse_app()` has no `stateless_http` parameter, so the defaulted-on setting
    # must never be forwarded to it.
    monkeypatch.setattr(settings, "mcp_transport", "sse")
    monkeypatch.setattr(settings, "mcp_stateless_http", True)

    app = main_module.build_http_app()

    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/sse" in paths
    assert "/messages" in paths or "/messages/" in paths
    assert app.router.lifespan_context.__name__ == "combined"


TOKEN = "s" * 32


@pytest.fixture
def auth_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "mcp_auth_token", SecretStr(TOKEN))


def _client(app) -> httpx.AsyncClient:
    # ASGITransport never runs the app lifespan, so no Qdrant connection is attempted.
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _has_auth_middleware(app) -> bool:
    return any(m.cls is BearerTokenMiddleware for m in app.user_middleware)


def test_build_http_app_has_no_auth_without_token(streamable_http, monkeypatch) -> None:
    monkeypatch.setattr(settings, "mcp_auth_token", None)

    assert not _has_auth_middleware(main_module.build_http_app())


@pytest.mark.parametrize("path", ["/mcp", "/reindex", "/reindex-history"])
async def test_build_http_app_requires_token(
    streamable_http, auth_token, path: str
) -> None:
    # The middleware answers before routing, so the routes need not be registered.
    async with _client(main_module.build_http_app()) as client:
        response = await client.post(path)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_build_http_app_sse_requires_token(auth_token, monkeypatch) -> None:
    monkeypatch.setattr(settings, "mcp_transport", "sse")

    async with _client(main_module.build_http_app()) as client:
        assert (await client.get("/sse")).status_code == 401
        assert (await client.post("/messages/")).status_code == 401


def test_build_http_app_with_token_keeps_lifespan(streamable_http, auth_token) -> None:
    app = main_module.build_http_app()

    assert _has_auth_middleware(app)
    assert app.router.lifespan_context.__name__ == "combined"


@pytest.mark.parametrize(
    ("host", "token", "warns"),
    [
        ("0.0.0.0", None, True),
        ("192.168.1.10", None, True),
        ("semcode.internal", None, True),
        ("127.0.0.1", None, False),
        ("::1", None, False),
        ("localhost", None, False),
        ("0.0.0.0", SecretStr(TOKEN), False),
    ],
)
def test_log_auth_posture_warns_when_exposed_without_token(
    streamable_http,
    monkeypatch,
    caplog,
    host: str,
    token: SecretStr | None,
    warns: bool,
) -> None:
    monkeypatch.setattr(settings, "mcp_host", host)
    monkeypatch.setattr(settings, "mcp_auth_token", token)

    with caplog.at_level(logging.INFO, logger=main_module.logger.name):
        main_module._log_auth_posture()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert bool(warnings) is warns


def test_log_auth_posture_notes_token_is_inert_with_stdio(monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "mcp_transport", "stdio")
    monkeypatch.setattr(settings, "mcp_host", "0.0.0.0")
    monkeypatch.setattr(settings, "mcp_auth_token", SecretStr(TOKEN))

    with caplog.at_level(logging.INFO, logger=main_module.logger.name):
        main_module._log_auth_posture()

    assert any("ignored" in r.getMessage() for r in caplog.records)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
