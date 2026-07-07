from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class PrunableStore(Protocol):
    """A store that can list indexed service names and delete all data for one."""

    async def get_indexed_services(self) -> list[str]: ...

    async def delete_by_service(self, service: str) -> None: ...


async def prune_orphaned_services(
    store: PrunableStore,
    configured_names: set[str],
    label: str = "data",
) -> list[str]:
    """Delete all stored data for services that exist in the store but not in
    the configured set. Returns the list of orphaned service names that were pruned."""
    indexed_names = await store.get_indexed_services()
    orphaned = set(indexed_names) - configured_names

    for name in sorted(orphaned):
        logger.warning("Pruning orphaned service %r from %s", name, label)
        await store.delete_by_service(name)

    return list(orphaned)
