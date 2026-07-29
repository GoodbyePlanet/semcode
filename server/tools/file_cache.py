from __future__ import annotations

from cachetools import TTLCache


class BlobContentCache:
    """LRU + TTL cache of file contents keyed on ``(repo, blob_sha)``.

    A git blob SHA is a content fingerprint, so an entry can only go stale in the
    sense that the *index* may have moved on to a newer blob — in which case the
    key changes and the old entry is simply never read again. The TTL exists only
    to bound memory for keys that fall out of use.

    Eviction and expiry are ``cachetools.TTLCache``; this wrapper only adds typed
    accessors and treats ``max_entries <= 0`` as "caching disabled" (TTLCache
    itself raises on insert when ``maxsize`` is 0). Not thread-safe — callers are
    expected to share one event loop, and nothing awaits between get and put.
    """

    def __init__(self, max_entries: int, ttl_seconds: float) -> None:
        self._cache: TTLCache[tuple[str, str], str] | None = (
            TTLCache(maxsize=max_entries, ttl=ttl_seconds) if max_entries > 0 else None
        )

    def get(self, repo: str, blob_sha: str) -> str | None:
        if self._cache is None:
            return None
        return self._cache.get((repo, blob_sha))

    def put(self, repo: str, blob_sha: str, content: str) -> None:
        if self._cache is None:
            return
        self._cache[(repo, blob_sha)] = content

    def clear(self) -> None:
        if self._cache is not None:
            self._cache.clear()
