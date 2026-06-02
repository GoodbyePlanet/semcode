from __future__ import annotations

from server.parser.compose import ComposeParser


def test_empty_file_returns_no_symbols() -> None:
    assert ComposeParser().parse_file(b"", "svc/docker-compose.yml") == []


def test_compose_without_services_returns_no_symbols() -> None:
    src = b"version: '3'\nvolumes:\n  data:\n"
    assert ComposeParser().parse_file(src, "svc/docker-compose.yml") == []


def test_canonical_compose_fixture(read_fixture) -> None:
    src = read_fixture("compose/docker-compose.yml")
    syms = ComposeParser().parse_file(src, "svc/docker-compose.yml")

    names = [s.name for s in syms]
    assert names == ["api", "qdrant"]

    api = syms[0]
    assert api.symbol_type == "service"
    assert api.language == "docker-compose"
    assert api.extras["image"] == "ghcr.io/example/api:latest"
    assert "qdrant" in api.extras["depends_on"]
    assert "PORT=8000" in api.extras["environment"]

    qdrant = syms[1]
    assert "6333:6333" in qdrant.extras["ports"]
    assert any("qdrant_data" in v for v in qdrant.extras["volumes"])
