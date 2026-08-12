from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from server.tools.index import register_index_tools
from tests.tools.conftest import get_tool


def _tool(name: str):
    return get_tool(register_index_tools, name)


async def test_reindex_unknown_service_lists_known_services() -> None:
    reindex = _tool("reindex")
    pipeline = AsyncMock()
    pipeline.index_service.return_value = {"error": 1, "files": 0, "chunks": 0}

    with (
        patch("server.tools.index.get_store", return_value=AsyncMock()),
        patch("server.tools.index.IndexPipeline", return_value=pipeline),
        patch("server.tools._services.get_service_registry"),
        patch(
            "server.tools._services.load_effective_services",
            AsyncMock(
                return_value=[
                    SimpleNamespace(name="orders"),
                    SimpleNamespace(name="catalog"),
                ]
            ),
        ),
    ):
        result = await reindex(service="unknown")

    assert result == "Service `unknown` not found. Known services: `catalog`, `orders`."


async def test_reindex_unknown_service_flags_empty_service_list() -> None:
    reindex = _tool("reindex")
    pipeline = AsyncMock()
    pipeline.index_service.return_value = {"error": 1, "files": 0, "chunks": 0}

    with (
        patch("server.tools.index.get_store", return_value=AsyncMock()),
        patch("server.tools.index.IndexPipeline", return_value=pipeline),
        patch("server.tools._services.get_service_registry"),
        patch(
            "server.tools._services.load_effective_services",
            AsyncMock(return_value=[]),
        ),
    ):
        result = await reindex(service="auth-server")

    assert "has no services at all" in result
    assert "never loaded" in result


async def test_reindex_single_service_reports_counts() -> None:
    reindex = _tool("reindex")
    pipeline = AsyncMock()
    pipeline.index_service.return_value = {"files": 3, "chunks": 12, "skipped": 5}

    with (
        patch("server.tools.index.get_store", return_value=AsyncMock()),
        patch("server.tools.index.IndexPipeline", return_value=pipeline),
    ):
        result = await reindex(service="orders", force=True)

    pipeline.index_service.assert_awaited_once_with("orders", force=True)
    assert "Files indexed: 3" in result
    assert "Chunks created: 12" in result
    assert "skipped (unchanged): 5" in result


async def test_reindex_all_services_aggregates_totals() -> None:
    reindex = _tool("reindex")
    pipeline = AsyncMock()
    pipeline.index_all.return_value = {
        "orders": {"files": 2, "chunks": 8, "skipped": 1},
        "catalog": {"files": 3, "chunks": 6, "skipped": 0},
    }

    with (
        patch("server.tools.index.get_store", return_value=AsyncMock()),
        patch("server.tools.index.IndexPipeline", return_value=pipeline),
    ):
        result = await reindex()

    pipeline.index_all.assert_awaited_once_with(force=False)
    assert "**orders**: 2 files, 8 chunks (1 skipped)" in result
    assert "**catalog**: 3 files, 6 chunks (0 skipped)" in result
    assert "**Total**: 5 files, 14 chunks" in result
