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
    the configured set. Returns the list of orphaned service names that were pruned.

    Refuses to prune when `configured_names` is empty — an empty configured set
    is far more likely to be a load error or operator mistake than a genuine
    intent to wipe every indexed service, and deletion is not reversible.
    """
    if not configured_names:
        logger.warning(
            "No configured services; skipping prune of %s to avoid wiping the store.",
            label,
        )
        return []

    indexed_names = await store.get_indexed_services()
    orphaned = sorted(set(indexed_names) - configured_names)

    for name in orphaned:
        logger.warning("Pruning orphaned service %r from %s", name, label)
        await store.delete_by_service(name)

    if orphaned:
        logger.info(
            "Pruned %d orphaned service(s) from %s: %s", len(orphaned), label, orphaned
        )

    return orphaned
