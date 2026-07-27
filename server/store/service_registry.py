from __future__ import annotations

import uuid
from datetime import UTC, datetime

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from server.config import ServiceConfig, settings

_COLLECTION = "service_registry"


def _service_point_id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"service_registry:{name}"))


def _to_service_config(payload: dict) -> ServiceConfig:
    return ServiceConfig(
        name=payload["name"],
        github_repo=payload["github_repo"],
        github_ref=payload.get("github_ref", "main"),
        root=payload.get("root"),
        exclude=payload.get("exclude") or [],
    )


class ServiceRegistry:
    """Persists ad-hoc service definitions registered inline through `POST /reindex`
    (`github_repo` in the body), so a repo can be indexed without a `config.yaml` entry.

    Registered services behave like `config.yaml` ones: they're picked up by
    `load_effective_services`, so they show up in `list_indexed_services`/`index_stats`
    and survive `index_all`'s orphan cleanup.
    """

    def __init__(self) -> None:
        self._client = AsyncQdrantClient(url=settings.qdrant_url)

    async def ensure_collection(self) -> None:
        if not await self._client.collection_exists(_COLLECTION):
            await self._client.create_collection(
                collection_name=_COLLECTION,
                vectors_config=VectorParams(size=1, distance=Distance.COSINE),
            )

    async def upsert(self, svc: ServiceConfig) -> None:
        await self.ensure_collection()
        await self._client.upsert(
            collection_name=_COLLECTION,
            points=[
                PointStruct(
                    id=_service_point_id(svc.name),
                    vector=[0.0],
                    payload={
                        "name": svc.name,
                        "github_repo": svc.github_repo,
                        "github_ref": svc.github_ref,
                        "root": svc.root,
                        "exclude": svc.exclude,
                        "registered_at": datetime.now(UTC).isoformat(),
                    },
                )
            ],
        )

    async def list_all(self) -> list[ServiceConfig]:
        if not await self._client.collection_exists(_COLLECTION):
            return []

        services: list[ServiceConfig] = []
        offset = None
        while True:
            results, offset = await self._client.scroll(
                collection_name=_COLLECTION,
                limit=1000,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            services.extend(_to_service_config(point.payload) for point in results)
            if offset is None:
                break
        return services

    async def close(self) -> None:
        await self._client.close()


async def load_effective_services(registry: ServiceRegistry) -> list[ServiceConfig]:
    """Merge config.yaml services with dynamically-registered ones.

    config.yaml wins on name collisions — it's the curated/authoritative source, so an
    inline registration can never silently repoint an existing configured service.
    """
    config_services = settings.load_services()
    registry_services = await registry.list_all()

    by_name = {s.name: s for s in registry_services}
    by_name.update({s.name: s for s in config_services})
    return list(by_name.values())
