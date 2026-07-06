from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx

from server.config import ServiceConfig
from tests.tools.conftest import StubHit, get_tool

from server.tools.search import register_search_tools


def _tool(name: str):
    return get_tool(register_search_tools, name)


async def test_search_code_reports_no_results() -> None:
    search_code = _tool("search_code")
    store = AsyncMock()
    store.search.return_value = []

    with (
        patch("server.tools.search.get_embedding_provider") as mock_embedder,
        patch("server.tools.search.get_sparse_provider") as mock_sparse,
        patch("server.tools.search.get_store", return_value=store),
    ):
        mock_embedder.return_value.embed_query = AsyncMock(return_value=[0.1])
        mock_sparse.return_value.embed_query = AsyncMock(return_value={})
        result = await search_code("find the order service")

    assert result == "No results found."


async def test_search_code_formats_hits() -> None:
    search_code = _tool("search_code")
    hit = StubHit(
        payload={
            "symbol_name": "PlaceOrder",
            "symbol_type": "method",
            "file_path": "orders/Order.java",
            "start_line": 10,
            "end_line": 20,
            "service": "orders",
            "language": "java",
            "annotations": ["Transactional"],
            "http_method": "POST",
            "http_route": "/orders",
            "signature": "void placeOrder()",
        },
        score=0.87,
    )
    store = AsyncMock()
    store.search.return_value = [hit]

    with (
        patch("server.tools.search.get_embedding_provider") as mock_embedder,
        patch("server.tools.search.get_sparse_provider") as mock_sparse,
        patch("server.tools.search.get_store", return_value=store),
    ):
        mock_embedder.return_value.embed_query = AsyncMock(return_value=[0.1])
        mock_sparse.return_value.embed_query = AsyncMock(return_value={})
        result = await search_code("place an order")

    assert "PlaceOrder" in result
    assert "orders/Order.java:10-20" in result
    assert "POST /orders" in result
    assert "Transactional" in result
    assert "0.870" in result


async def test_find_symbol_reports_no_match() -> None:
    find_symbol = _tool("find_symbol")
    store = AsyncMock()
    store.find_by_name.return_value = []

    with patch("server.tools.search.get_store", return_value=store):
        result = await find_symbol("Nope")

    assert result == "No symbol found matching `Nope`."


async def test_find_symbol_formats_match_with_parent() -> None:
    find_symbol = _tool("find_symbol")
    hit = StubHit(
        payload={
            "symbol_name": "placeOrder",
            "symbol_type": "method",
            "file_path": "orders/OrderService.java",
            "start_line": 5,
            "end_line": 9,
            "service": "orders",
            "package": "com.example.orders",
            "parent_name": "OrderService",
            "language": "java",
            "source": "void placeOrder() {}",
        }
    )
    store = AsyncMock()
    store.find_by_name.return_value = [hit]

    with patch("server.tools.search.get_store", return_value=store):
        result = await find_symbol("placeOrder", exact=True)

    assert "`placeOrder`" in result
    assert "**Parent**: `OrderService`" in result
    store.find_by_name.assert_awaited_once_with(
        name="placeOrder", symbol_type=None, service=None, exact=True
    )


async def test_find_usages_excludes_hits_matching_symbol_itself() -> None:
    find_usages = _tool("find_usages")
    self_hit = StubHit(payload={"symbol_name": "OrderService", "source": ""})
    caller_hit = StubHit(
        payload={
            "symbol_name": "placeOrder",
            "file_path": "orders/Controller.java",
            "start_line": 1,
            "service": "orders",
            "source": "OrderService svc = new OrderService();",
            "language": "java",
        }
    )
    store = AsyncMock()
    store.search.return_value = [self_hit, caller_hit]

    with (
        patch("server.tools.search.get_embedding_provider") as mock_embedder,
        patch("server.tools.search.get_sparse_provider") as mock_sparse,
        patch("server.tools.search.get_store", return_value=store),
    ):
        mock_embedder.return_value.embed_query = AsyncMock(return_value=[0.1])
        mock_sparse.return_value.embed_query = AsyncMock(return_value={})
        result = await find_usages("OrderService")

    assert "Found 1 usage(s)" in result
    assert "Controller.java" in result


async def test_find_usages_can_undercount_when_all_fetched_hits_are_self_matches() -> (
    None
):
    # Known limitation: `limit` bounds the initial fetch from the store, and
    # self-matches are filtered out *after* that fetch rather than being
    # excluded from the query itself. If every fetched hit is a self-match,
    # zero usages are reported even though usages may exist beyond the
    # fetched window.
    find_usages = _tool("find_usages")
    store = AsyncMock()
    store.search.return_value = [
        StubHit(payload={"symbol_name": "OrderService", "source": ""})
    ]

    with (
        patch("server.tools.search.get_embedding_provider") as mock_embedder,
        patch("server.tools.search.get_sparse_provider") as mock_sparse,
        patch("server.tools.search.get_store", return_value=store),
    ):
        mock_embedder.return_value.embed_query = AsyncMock(return_value=[0.1])
        mock_sparse.return_value.embed_query = AsyncMock(return_value={})
        result = await find_usages("OrderService", limit=1)

    assert result == "No usages of `OrderService` found."


async def test_find_usages_snippet_windows_around_match() -> None:
    find_usages = _tool("find_usages")
    source = ("x" * 150) + "OrderService" + ("y" * 250)
    hit = StubHit(
        payload={
            "symbol_name": "placeOrder",
            "file_path": "orders/Controller.java",
            "start_line": 1,
            "service": "orders",
            "source": source,
            "language": "java",
        }
    )
    store = AsyncMock()
    store.search.return_value = [hit]

    with (
        patch("server.tools.search.get_embedding_provider") as mock_embedder,
        patch("server.tools.search.get_sparse_provider") as mock_sparse,
        patch("server.tools.search.get_store", return_value=store),
    ):
        mock_embedder.return_value.embed_query = AsyncMock(return_value=[0.1])
        mock_sparse.return_value.embed_query = AsyncMock(return_value={})
        result = await find_usages("OrderService")

    idx = source.find("OrderService")
    expected_snippet = source[idx - 100 : idx + len("OrderService") + 200]
    assert expected_snippet in result


async def test_get_code_context_file_not_in_index() -> None:
    get_code_context = _tool("get_code_context")
    store = AsyncMock()
    store.get_file_info.return_value = None

    with patch("server.tools.search.get_store", return_value=store):
        result = await get_code_context("orders/Order.java")

    assert result == "File not found in index: `orders/Order.java`"


async def test_get_code_context_service_removed_from_config() -> None:
    get_code_context = _tool("get_code_context")
    store = AsyncMock()
    store.get_file_info.return_value = {"service": "orders"}

    with (
        patch("server.tools.search.get_store", return_value=store),
        patch("server.tools.search.settings") as mock_settings,
    ):
        mock_settings.load_services.return_value = []
        result = await get_code_context("orders/Order.java")

    assert result == "Service `orders` is no longer in config.yaml."


async def test_get_code_context_reconstructs_path_with_root_prefix() -> None:
    get_code_context = _tool("get_code_context")
    store = AsyncMock()
    store.get_file_info.return_value = {"service": "orders"}
    store.find_by_name.return_value = []
    svc = ServiceConfig(
        name="orders",
        github_repo="org/orders",
        exclude=[],
        root="services/orders",
    )

    with (
        patch("server.tools.search.get_store", return_value=store),
        patch("server.tools.search.settings") as mock_settings,
        patch(
            "server.tools.search.fetch_file_content", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_settings.load_services.return_value = [svc]
        mock_settings.github_token = "token"
        mock_fetch.return_value = b"class Order {}"

        await get_code_context("orders/src/Order.java")

    mock_fetch.assert_awaited_once_with(
        "token", "org/orders", "services/orders/src/Order.java", svc.github_ref
    )


async def test_get_code_context_returns_full_file_without_symbol_name() -> None:
    get_code_context = _tool("get_code_context")
    store = AsyncMock()
    store.get_file_info.return_value = {"service": "orders"}
    svc = ServiceConfig(name="orders", github_repo="org/orders", exclude=[])

    with (
        patch("server.tools.search.get_store", return_value=store),
        patch("server.tools.search.settings") as mock_settings,
        patch(
            "server.tools.search.fetch_file_content", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_settings.load_services.return_value = [svc]
        mock_settings.github_token = "token"
        mock_fetch.return_value = b"class Order {}"

        result = await get_code_context("orders/Order.java")

    assert result == "```\nclass Order {}\n```"


async def test_get_code_context_github_fetch_error_is_reported() -> None:
    get_code_context = _tool("get_code_context")
    store = AsyncMock()
    store.get_file_info.return_value = {"service": "orders"}
    svc = ServiceConfig(name="orders", github_repo="org/orders", exclude=[])

    with (
        patch("server.tools.search.get_store", return_value=store),
        patch("server.tools.search.settings") as mock_settings,
        patch(
            "server.tools.search.fetch_file_content", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_settings.load_services.return_value = [svc]
        mock_settings.github_token = "token"
        mock_fetch.side_effect = httpx.HTTPError("boom")

        result = await get_code_context("orders/Order.java")

    assert "Failed to fetch `orders/Order.java`" in result


async def test_get_code_context_uses_qdrant_line_numbers_for_symbol() -> None:
    get_code_context = _tool("get_code_context")
    store = AsyncMock()
    store.get_file_info.return_value = {"service": "orders"}
    store.find_by_name.return_value = [
        StubHit(
            payload={
                "file_path": "orders/Order.java",
                "symbol_type": "method",
                "start_line": 2,
                "end_line": 3,
                "language": "java",
            }
        )
    ]
    svc = ServiceConfig(name="orders", github_repo="org/orders", exclude=[])
    content = b"line1\nvoid placeOrder() {\n}\nline4"

    with (
        patch("server.tools.search.get_store", return_value=store),
        patch("server.tools.search.settings") as mock_settings,
        patch(
            "server.tools.search.fetch_file_content", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_settings.load_services.return_value = [svc]
        mock_settings.github_token = "token"
        mock_fetch.return_value = content

        result = await get_code_context("orders/Order.java", symbol_name="placeOrder")

    assert "at `orders/Order.java`:2-3" in result
    assert "void placeOrder() {\n}" in result


async def test_get_code_context_falls_back_to_text_search_when_symbol_not_in_index() -> (
    None
):
    get_code_context = _tool("get_code_context")
    store = AsyncMock()
    store.get_file_info.return_value = {"service": "orders"}
    store.find_by_name.return_value = []
    svc = ServiceConfig(name="orders", github_repo="org/orders", exclude=[])
    content = b"line1\nvoid placeOrder() {}\nline3"

    with (
        patch("server.tools.search.get_store", return_value=store),
        patch("server.tools.search.settings") as mock_settings,
        patch(
            "server.tools.search.fetch_file_content", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_settings.load_services.return_value = [svc]
        mock_settings.github_token = "token"
        mock_fetch.return_value = content

        result = await get_code_context("orders/Order.java", symbol_name="placeOrder")

    assert "Found `placeOrder` near line 2" in result


async def test_get_code_context_symbol_not_found_anywhere() -> None:
    get_code_context = _tool("get_code_context")
    store = AsyncMock()
    store.get_file_info.return_value = {"service": "orders"}
    store.find_by_name.return_value = []
    svc = ServiceConfig(name="orders", github_repo="org/orders", exclude=[])

    with (
        patch("server.tools.search.get_store", return_value=store),
        patch("server.tools.search.settings") as mock_settings,
        patch(
            "server.tools.search.fetch_file_content", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_settings.load_services.return_value = [svc]
        mock_settings.github_token = "token"
        mock_fetch.return_value = b"nothing relevant here"

        result = await get_code_context("orders/Order.java", symbol_name="placeOrder")

    assert result == "`placeOrder` not found in `orders/Order.java`."
