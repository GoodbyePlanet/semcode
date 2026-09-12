from __future__ import annotations

import pytest

from server import main as main_module
from server.config import settings


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
