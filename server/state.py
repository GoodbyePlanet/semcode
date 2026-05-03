from __future__ import annotations

from server.embeddings.bm25 import BM25SparseProvider
from server.store.commit_store import CommitStore
from server.store.qdrant import QdrantStore

_store: QdrantStore | None = None
_commit_store: CommitStore | None = None
_sparse_provider: BM25SparseProvider | None = None


def get_store() -> QdrantStore:
    if _store is None:
        raise RuntimeError("Store not initialized")
    return _store


def set_store(store: QdrantStore) -> None:
    global _store
    _store = store


def get_commit_store() -> CommitStore:
    if _commit_store is None:
        raise RuntimeError("Commit store not initialized")
    return _commit_store


def set_commit_store(store: CommitStore) -> None:
    global _commit_store
    _commit_store = store


def get_sparse_provider() -> BM25SparseProvider:
    if _sparse_provider is None:
        raise RuntimeError("Sparse embedding provider not initialized")
    return _sparse_provider


def set_sparse_provider(provider: BM25SparseProvider) -> None:
    global _sparse_provider
    _sparse_provider = provider
