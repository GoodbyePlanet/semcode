from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from qdrant_client.models import (
    FieldCondition,
    Fusion,
    FusionQuery,
    SparseVector,
    TextIndexParams,
    TokenizerType,
)

from server.store.qdrant import SYMBOL_TOKENS_FIELD, QdrantStore


def _make_record(symbol_name: str) -> SimpleNamespace:
    return SimpleNamespace(payload={"symbol_name": symbol_name})


def test_close_is_coroutine() -> None:
    """close() must be awaitable — regression for unawaited call in lifespan."""
    assert asyncio.iscoroutinefunction(QdrantStore.close)


async def test_get_indexed_services_excludes_unknown_placeholder() -> None:
    """The 'unknown' placeholder from unlabeled payloads must never look like a
    real service name that pruning could delete."""
    store = QdrantStore.__new__(QdrantStore)
    store.get_service_stats = AsyncMock(
        return_value=[
            {"service": "billing", "symbols": 3},
            {"service": "unknown", "symbols": 1},
        ]
    )

    services = await store.get_indexed_services()

    assert services == ["billing"]


async def test_find_by_name_fuzzy_queries_the_text_index() -> None:
    """Non-exact search must filter server-side instead of scanning the collection."""
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"

    store._client = MagicMock()
    store._client.scroll = AsyncMock(
        return_value=([_make_record("target_gamma")], None)
    )

    results = await store.find_by_name("target", exact=False)

    assert store._client.scroll.call_count == 1
    scroll_filter = store._client.scroll.call_args.kwargs["scroll_filter"]
    assert any(
        isinstance(c, FieldCondition)
        and c.key == SYMBOL_TOKENS_FIELD
        and c.match.text == "target"
        for c in scroll_filter.must
    )
    assert [r.payload["symbol_name"] for r in results] == ["target_gamma"]


async def test_find_by_name_fuzzy_keeps_other_filters_alongside_text_match() -> None:
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"

    store._client = MagicMock()
    store._client.scroll = AsyncMock(
        return_value=([_make_record("target_gamma")], None)
    )

    await store.find_by_name("target", exact=False, service="billing")

    scroll_filter = store._client.scroll.call_args.kwargs["scroll_filter"]
    keys = {c.key for c in scroll_filter.must if isinstance(c, FieldCondition)}
    assert keys == {"service", SYMBOL_TOKENS_FIELD}


async def test_find_by_name_fuzzy_falls_back_to_scanning_when_index_misses() -> None:
    """Collections indexed before symbol_name_tokens existed have nothing for
    MatchText to hit, so lookups must still resolve via the paginated scan."""
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"

    page1 = [_make_record("unrelated_alpha"), _make_record("unrelated_beta")]
    page2 = [_make_record("target_gamma"), _make_record("unrelated_delta")]

    store._client = MagicMock()
    store._client.scroll = AsyncMock(
        side_effect=[
            ([], None),  # text index returns nothing
            (page1, "cursor_page2"),
            (page2, None),
        ]
    )

    results = await store.find_by_name("arget", exact=False)

    assert store._client.scroll.call_count == 3
    assert len(results) == 1
    assert results[0].payload["symbol_name"] == "target_gamma"


async def test_find_by_name_ranks_exact_then_prefix_matches_first() -> None:
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"

    # Qdrant returns points in id order, which buries the exact match.
    records = [
        _make_record("findOrderById"),
        _make_record("OrderService"),
        _make_record("Order"),
    ]
    store._client = MagicMock()
    store._client.scroll = AsyncMock(return_value=(records, None))

    results = await store.find_by_name("order", exact=False)

    assert [r.payload["symbol_name"] for r in results] == [
        "Order",
        "OrderService",
        "findOrderById",
    ]


async def test_find_by_name_exact_does_not_paginate() -> None:
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"

    record = _make_record("MyService")
    store._client = MagicMock()
    store._client.scroll = AsyncMock(return_value=([record], None))

    results = await store.find_by_name("MyService", exact=True)

    assert store._client.scroll.call_count == 1
    assert results[0].payload["symbol_name"] == "MyService"


async def test_search_uses_prefetch_and_rrf() -> None:
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"

    fake_result = MagicMock()
    fake_result.points = []
    store._client = MagicMock()
    store._client.query_points = AsyncMock(return_value=fake_result)

    dense = [0.1] * 768
    sparse = SparseVector(indices=[1, 2], values=[0.5, 0.3])

    await store.search(dense_vector=dense, sparse_vector=sparse, limit=5)

    store._client.query_points.assert_called_once()
    kwargs = store._client.query_points.call_args.kwargs

    prefetches = kwargs["prefetch"]
    assert len(prefetches) == 2

    usings = {p.using for p in prefetches}
    assert usings == {"text-dense", "text-sparse"}

    for p in prefetches:
        assert p.limit == 10  # limit * 2

    assert isinstance(kwargs["query"], FusionQuery)
    assert kwargs["query"].fusion == Fusion.RRF


async def test_search_filters_by_chunk_tier() -> None:
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"

    fake_result = MagicMock()
    fake_result.points = []
    store._client = MagicMock()
    store._client.query_points = AsyncMock(return_value=fake_result)

    dense = [0.1] * 768
    sparse = SparseVector(indices=[1, 2], values=[0.5, 0.3])

    await store.search(
        dense_vector=dense, sparse_vector=sparse, limit=5, chunk_tier="method"
    )

    kwargs = store._client.query_points.call_args.kwargs
    for prefetch in kwargs["prefetch"]:
        conditions = prefetch.filter.must
        assert any(
            isinstance(c, FieldCondition)
            and c.key == "chunk_tier"
            and c.match.value == "method"
            for c in conditions
        )


async def test_find_by_name_filters_by_chunk_tier() -> None:
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"

    record = _make_record("MyService")
    store._client = MagicMock()
    store._client.scroll = AsyncMock(return_value=([record], None))

    await store.find_by_name("MyService", exact=True, chunk_tier="class")

    scroll_filter = store._client.scroll.call_args.kwargs["scroll_filter"]
    assert any(
        isinstance(c, FieldCondition)
        and c.key == "chunk_tier"
        and c.match.value == "class"
        for c in scroll_filter.must
    )


async def test_ensure_collection_indexes_existing_collection() -> None:
    """Indexes added in later versions must reach collections created before them."""
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"
    store._dimensions = 1024
    store._client = MagicMock()
    store._client.collection_exists = AsyncMock(return_value=True)
    store._client.create_collection = AsyncMock()
    store._client.create_payload_index = AsyncMock()
    store._validate_dimensions = AsyncMock()

    await store.ensure_collection()

    store._client.create_collection.assert_not_awaited()
    indexed_fields = {
        call.kwargs["field_name"]
        for call in store._client.create_payload_index.call_args_list
    }
    assert "symbol_name" in indexed_fields
    assert SYMBOL_TOKENS_FIELD in indexed_fields


async def test_symbol_name_tokens_index_uses_prefix_tokenizer() -> None:
    """A partial query ('Ord') must match a full token ('Order')."""
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"
    store._client = MagicMock()
    store._client.create_payload_index = AsyncMock()

    await store._create_payload_indexes()

    schema = next(
        call.kwargs["field_schema"]
        for call in store._client.create_payload_index.call_args_list
        if call.kwargs["field_name"] == SYMBOL_TOKENS_FIELD
    )
    assert isinstance(schema, TextIndexParams)
    assert schema.tokenizer == TokenizerType.PREFIX
    assert schema.lowercase is True
