from __future__ import annotations

from server.tools.file_cache import BlobContentCache


def test_put_then_get_returns_content() -> None:
    cache = BlobContentCache(max_entries=2, ttl_seconds=60)
    cache.put("org/orders", "blob1", "class Order {}")

    assert cache.get("org/orders", "blob1") == "class Order {}"


def test_get_missing_key_returns_none() -> None:
    cache = BlobContentCache(max_entries=2, ttl_seconds=60)

    assert cache.get("org/orders", "blob1") is None


def test_same_blob_sha_in_different_repos_is_a_separate_entry() -> None:
    cache = BlobContentCache(max_entries=2, ttl_seconds=60)
    cache.put("org/orders", "blob1", "orders")

    assert cache.get("org/billing", "blob1") is None


def test_expired_entry_is_evicted_on_read() -> None:
    cache = BlobContentCache(max_entries=2, ttl_seconds=0)
    cache.put("org/orders", "blob1", "class Order {}")

    assert cache.get("org/orders", "blob1") is None


def test_least_recently_used_entry_is_evicted_when_full() -> None:
    cache = BlobContentCache(max_entries=2, ttl_seconds=60)
    cache.put("org/orders", "blob1", "one")
    cache.put("org/orders", "blob2", "two")
    cache.get("org/orders", "blob1")  # blob2 is now least recently used
    cache.put("org/orders", "blob3", "three")

    assert cache.get("org/orders", "blob2") is None
    assert cache.get("org/orders", "blob1") == "one"
    assert cache.get("org/orders", "blob3") == "three"


def test_zero_max_entries_disables_caching() -> None:
    cache = BlobContentCache(max_entries=0, ttl_seconds=60)
    cache.put("org/orders", "blob1", "one")

    assert cache.get("org/orders", "blob1") is None


def test_clear_drops_all_entries() -> None:
    cache = BlobContentCache(max_entries=2, ttl_seconds=60)
    cache.put("org/orders", "blob1", "one")
    cache.clear()

    assert cache.get("org/orders", "blob1") is None
