from __future__ import annotations

from server.store.commit_store import CommitStore
from server.store.qdrant import QdrantStore

_store: QdrantStore | None = None
_commit_store: CommitStore | None = None
_reranker = None


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


def get_reranker():
    if _reranker is None:
        raise RuntimeError("Reranker not initialized")
    return _reranker


def set_reranker(reranker) -> None:
    global _reranker
    _reranker = reranker
