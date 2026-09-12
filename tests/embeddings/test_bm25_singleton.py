from __future__ import annotations

import pytest

import server.embeddings.bm25 as bm25_module
import server.indexer.pipeline as pipeline_module
import server.tools.search as search_module
from server.embeddings.bm25 import (
    close_sparse_embedding_provider,
    get_sparse_embedding_provider,
)


class _StubBm25:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name


@pytest.fixture(autouse=True)
def stub_model(monkeypatch):
    """Keep the tests off the real fastembed model download."""
    monkeypatch.setattr(bm25_module, "Bm25", _StubBm25)
    monkeypatch.setattr(bm25_module, "_provider", None)


def test_get_sparse_embedding_provider_returns_singleton() -> None:
    assert get_sparse_embedding_provider() is get_sparse_embedding_provider()


def test_indexing_and_search_share_one_instance() -> None:
    """Guards against reintroducing a second BM25 holder (issue #70): the
    pipeline and the search tools must resolve to the same model."""
    assert (
        pipeline_module.get_sparse_embedding_provider
        is search_module.get_sparse_embedding_provider
    )
    assert (
        pipeline_module.get_sparse_embedding_provider()
        is search_module.get_sparse_embedding_provider()
    )


async def test_close_releases_the_only_instance() -> None:
    provider = get_sparse_embedding_provider()

    await close_sparse_embedding_provider()

    assert bm25_module._provider is None
    assert get_sparse_embedding_provider() is not provider
