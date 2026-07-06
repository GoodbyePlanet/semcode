from __future__ import annotations

from unittest.mock import AsyncMock, patch

from server.tools.history import register_history_tools
from tests.tools.conftest import StubHit, get_tool


def _tool(name: str):
    return get_tool(register_history_tools, name)


async def test_search_commits_reports_no_results() -> None:
    search_commits = _tool("search_commits")
    store = AsyncMock()
    store.search.return_value = []

    with (
        patch("server.tools.history.get_embedding_provider") as mock_embedder,
        patch("server.tools.history.get_commit_store", return_value=store),
    ):
        mock_embedder.return_value.embed_query = AsyncMock(return_value=[0.1])
        result = await search_commits("fix the bug")

    assert result == "No commits found."


async def test_search_commits_formats_hits() -> None:
    search_commits = _tool("search_commits")
    hit = StubHit(
        payload={
            "sha": "abcdef1234567890",
            "service": "orders",
            "author_name": "Ana",
            "committed_at": "2026-01-01T00:00:00Z",
            "message": "Fix order total calculation",
        },
        score=0.5,
    )
    store = AsyncMock()
    store.search.return_value = [hit]

    with (
        patch("server.tools.history.get_embedding_provider") as mock_embedder,
        patch("server.tools.history.get_commit_store", return_value=store),
    ):
        mock_embedder.return_value.embed_query = AsyncMock(return_value=[0.1])
        result = await search_commits("fix order total")

    assert "`abcdef12`" in result
    assert "Fix order total calculation" in result


async def test_get_commit_not_found() -> None:
    get_commit = _tool("get_commit")
    store = AsyncMock()
    store.get_commit_by_sha.return_value = None

    with patch("server.tools.history.get_commit_store", return_value=store):
        result = await get_commit("deadbeef")

    assert "not found in index" in result


async def test_get_commit_reports_no_diff_data() -> None:
    get_commit = _tool("get_commit")
    store = AsyncMock()
    store.get_commit_by_sha.return_value = {
        "sha": "deadbeef" * 5,
        "service": "orders",
        "author_name": "Ana",
        "author_email": "ana@example.com",
        "committed_at": "2026-01-01",
        "message": "Initial commit",
        "files": [],
    }

    with patch("server.tools.history.get_commit_store", return_value=store):
        result = await get_commit("deadbeef")

    assert "No diff data available" in result


async def test_get_commit_formats_changed_files_and_truncation() -> None:
    get_commit = _tool("get_commit")
    store = AsyncMock()
    store.get_commit_by_sha.return_value = {
        "sha": "deadbeef" * 5,
        "service": "orders",
        "author_name": "Ana",
        "author_email": "ana@example.com",
        "committed_at": "2026-01-01",
        "message": "Refactor order flow",
        "files": [
            {
                "filename": "Order.java",
                "status": "modified",
                "additions": 10,
                "deletions": 2,
                "patch": "@@ -1 +1 @@",
            }
        ],
        "diff_truncated": True,
    }

    with patch("server.tools.history.get_commit_store", return_value=store):
        result = await get_commit("deadbeef")

    assert "Order.java" in result
    assert "+10 -2" in result
    assert "Diff truncated" in result


async def test_index_history_reports_unknown_service() -> None:
    index_history = _tool("index_history")
    pipeline = AsyncMock()
    pipeline.index_service.return_value = {"error": 1}

    with (
        patch("server.tools.history.get_commit_store", return_value=AsyncMock()),
        patch("server.tools.history.GitHistoryPipeline", return_value=pipeline),
    ):
        result = await index_history(service="unknown")

    assert result == "Service `unknown` not found in config.yaml."


async def test_index_history_single_service_reports_diff_updates() -> None:
    index_history = _tool("index_history")
    pipeline = AsyncMock()
    pipeline.index_service.return_value = {"new": 3, "skipped": 1, "diff_updated": 2}

    with (
        patch("server.tools.history.get_commit_store", return_value=AsyncMock()),
        patch("server.tools.history.GitHistoryPipeline", return_value=pipeline),
    ):
        result = await index_history(service="orders")

    assert "New commits: 3" in result
    assert "Skipped (already indexed): 1" in result
    assert "Diffs fetched for existing commits: 2" in result


async def test_index_history_all_services_aggregates_new_commits() -> None:
    index_history = _tool("index_history")
    pipeline = AsyncMock()
    pipeline.index_all.return_value = {
        "orders": {"new": 2, "skipped": 0},
        "catalog": {"new": 5, "skipped": 1, "diff_updated": 1},
    }

    with (
        patch("server.tools.history.get_commit_store", return_value=AsyncMock()),
        patch("server.tools.history.GitHistoryPipeline", return_value=pipeline),
    ):
        result = await index_history()

    assert "**orders**: 2 new commits (0 skipped)" in result
    assert "**catalog**: 5 new commits (1 skipped), 1 diffs updated" in result
    assert "**Total**: 7 new commits" in result
