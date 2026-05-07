from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from qdrant_client.models import Fusion, SparseVector

from server.store.qdrant import QdrantStore


def _make_record(symbol_name: str) -> SimpleNamespace:
    return SimpleNamespace(payload={"symbol_name": symbol_name})


def test_close_is_coroutine():
    """close() must be awaitable — regression for unawaited call in lifespan."""
    assert asyncio.iscoroutinefunction(QdrantStore.close)


async def test_find_by_name_fuzzy_scans_all_pages():
    """Non-exact search must paginate instead of relying on the first 20 results."""
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"

    page1 = [_make_record("unrelated_alpha"), _make_record("unrelated_beta")]
    page2 = [_make_record("target_gamma"), _make_record("unrelated_delta")]

    store._client = MagicMock()
    store._client.scroll = AsyncMock(
        side_effect=[
            (page1, "cursor_page2"),
            (page2, None),
        ]
    )

    results = await store.find_by_name("target", exact=False)

    assert store._client.scroll.call_count == 2
    assert len(results) == 1
    assert results[0].payload["symbol_name"] == "target_gamma"


async def test_find_by_name_exact_does_not_paginate():
    """Exact search uses a single scroll call with a MatchValue filter."""
    store = QdrantStore.__new__(QdrantStore)
    store._collection = "test"

    record = _make_record("MyService")
    store._client = MagicMock()
    store._client.scroll = AsyncMock(return_value=([record], None))

    results = await store.find_by_name("MyService", exact=True)

    assert store._client.scroll.call_count == 1
    assert results[0].payload["symbol_name"] == "MyService"


async def test_search_uses_prefetch_and_rrf():
    """search() must issue two Prefetch clauses (dense + sparse) fused with RRF."""
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

    from qdrant_client.models import FusionQuery

    assert isinstance(kwargs["query"], FusionQuery)
    assert kwargs["query"].fusion == Fusion.RRF
