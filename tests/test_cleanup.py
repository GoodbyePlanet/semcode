from __future__ import annotations

from server.indexer.cleanup import prune_orphaned_services


class _FakeStore:
    def __init__(self, indexed_names: list[str]) -> None:
        self.indexed_names = indexed_names
        self.deleted: list[str] = []

    async def get_indexed_services(self) -> list[str]:
        return self.indexed_names

    async def delete_by_service(self, service: str) -> None:
        self.deleted.append(service)


async def test_service_absent_from_config_is_deleted() -> None:
    store = _FakeStore(["kept", "renamed-away"])

    orphaned = await prune_orphaned_services(store, {"kept"})

    assert orphaned == ["renamed-away"]
    assert store.deleted == ["renamed-away"]


async def test_configured_service_is_never_deleted() -> None:
    store = _FakeStore(["kept"])

    orphaned = await prune_orphaned_services(store, {"kept"})

    assert orphaned == []
    assert store.deleted == []


async def test_empty_configured_names_skips_prune_entirely() -> None:
    store = _FakeStore(["a", "b", "c"])

    orphaned = await prune_orphaned_services(store, set())

    assert orphaned == []
    assert store.deleted == []


async def test_no_indexed_services_is_a_noop() -> None:
    store = _FakeStore([])

    orphaned = await prune_orphaned_services(store, {"kept"})

    assert orphaned == []
    assert store.deleted == []


async def test_multiple_orphans_are_returned_sorted() -> None:
    store = _FakeStore(["zeta", "alpha", "kept", "beta"])

    orphaned = await prune_orphaned_services(store, {"kept"})

    assert orphaned == ["alpha", "beta", "zeta"]
    assert store.deleted == ["alpha", "beta", "zeta"]
