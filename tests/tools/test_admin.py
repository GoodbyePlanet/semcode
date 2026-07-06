from __future__ import annotations

from unittest.mock import AsyncMock, patch

from server.config import ServiceConfig
from server.tools.admin import register_admin_tools
from tests.tools.conftest import get_tool


def _tool(name: str):
    return get_tool(register_admin_tools, name)


async def test_list_indexed_services_reports_when_empty() -> None:
    list_indexed_services = _tool("list_indexed_services")
    store = AsyncMock()
    store.get_service_stats.return_value = []

    with patch("server.tools.admin.get_store", return_value=store):
        result = await list_indexed_services()

    assert "No services indexed yet" in result


async def test_list_indexed_services_formats_stats_sorted_by_name() -> None:
    list_indexed_services = _tool("list_indexed_services")
    store = AsyncMock()
    store.get_service_stats.return_value = [
        {
            "service": "zebra",
            "chunk_count": 5,
            "file_count": 2,
            "languages": ["python"],
            "last_indexed": "2026-01-01",
        },
        {
            "service": "alpha",
            "chunk_count": 10,
            "file_count": 4,
            "languages": ["java", "python"],
            "last_indexed": "2026-01-02",
        },
    ]

    with patch("server.tools.admin.get_store", return_value=store):
        result = await list_indexed_services()

    assert result.index("alpha") < result.index("zebra")
    assert "Chunks: 10" in result


async def test_index_stats_reports_qdrant_error() -> None:
    index_stats = _tool("index_stats")
    store = AsyncMock()
    store.collection_info.side_effect = RuntimeError("connection refused")

    with (
        patch("server.tools.admin.get_store", return_value=store),
        patch("server.tools.admin.settings") as mock_settings,
    ):
        mock_settings.load_services.return_value = []
        result = await index_stats()

    assert "Could not reach Qdrant" in result
    assert "connection refused" in result


async def test_index_stats_includes_provider_endpoint() -> None:
    index_stats = _tool("index_stats")
    store = AsyncMock()
    store.collection_info.return_value = {
        "collection": "code_symbols",
        "total_vectors": 100,
        "vector_size": 768,
        "status": "green",
    }
    svc = ServiceConfig(name="orders", github_repo="org/orders", exclude=[])

    with (
        patch("server.tools.admin.get_store", return_value=store),
        patch("server.tools.admin.settings") as mock_settings,
    ):
        mock_settings.load_services.return_value = [svc]
        mock_settings.embeddings_provider = "voyage"
        result = await index_stats()

    assert "**Embeddings provider**: voyage" in result
    assert "https://api.voyageai.com/v1/embeddings" in result
    assert "`orders` — `org/orders@main`" in result
