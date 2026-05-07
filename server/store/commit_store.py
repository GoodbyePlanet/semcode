from __future__ import annotations

import asyncio
import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    OptimizersConfigDiff,
    PayloadSchemaType,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from server.config import settings


def _commit_point_id(service: str, sha: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{service}:{sha}"))


class CommitStore:
    def __init__(self) -> None:
        self._client = AsyncQdrantClient(url=settings.qdrant_url)
        self._collection = settings.qdrant_commits_collection

    async def ensure_collection(self) -> None:
        exists = await self._client.collection_exists(self._collection)
        if not exists:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(
                    size=settings.embeddings_dimensions,
                    distance=Distance.COSINE,
                ),
                optimizers_config=OptimizersConfigDiff(indexing_threshold=500),
                hnsw_config=HnswConfigDiff(m=16, ef_construct=128),
            )
        await self._create_payload_indexes()

    async def _create_payload_indexes(self) -> None:
        for field_name in ["service", "author_name", "sha"]:
            await self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        await self._client.create_payload_index(
            collection_name=self._collection,
            field_name="has_diff",
            field_schema=PayloadSchemaType.BOOL,
        )

    async def get_indexed_shas(self, service: str) -> set[str]:
        shas: set[str] = set()
        offset = None
        while True:
            results, offset = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(key="service", match=MatchValue(value=service))
                    ]
                ),
                limit=1000,
                offset=offset,
                with_payload=["sha"],
                with_vectors=False,
            )
            for point in results:
                sha = point.payload.get("sha")
                if sha:
                    shas.add(sha)
            if offset is None:
                break
        return shas

    async def upsert_commits(
        self,
        service: str,
        payloads: list[dict[str, Any]],
        vectors: list[list[float]],
    ) -> None:
        points = [
            PointStruct(id=_commit_point_id(service, p["sha"]), vector=v, payload=p)
            for p, v in zip(payloads, vectors)
        ]
        if points:
            await self._client.upsert(collection_name=self._collection, points=points)

    async def search(
        self,
        query_vector: list[float],
        service: str | None = None,
        limit: int = 10,
    ) -> list[ScoredPoint]:
        must = []
        if service:
            must.append(FieldCondition(key="service", match=MatchValue(value=service)))
        query_filter = Filter(must=must) if must else None
        result = await self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return result.points

    async def get_commit_count(self, service: str | None = None) -> int:
        must = []
        if service:
            must.append(FieldCondition(key="service", match=MatchValue(value=service)))
        count_filter = Filter(must=must) if must else None
        result = await self._client.count(
            collection_name=self._collection,
            count_filter=count_filter,
            exact=True,
        )
        return result.count

    async def get_commit_by_sha(
        self, sha: str, service: str | None = None
    ) -> dict[str, Any] | None:
        must = [FieldCondition(key="sha", match=MatchValue(value=sha))]
        if service:
            must.append(FieldCondition(key="service", match=MatchValue(value=service)))
        results, _ = await self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(must=must),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if results:
            return results[0].payload

        # Fall back to prefix matching for short SHAs
        must = []
        if service:
            must.append(FieldCondition(key="service", match=MatchValue(value=service)))
        query_filter = Filter(must=must) if must else None
        offset = None
        while True:
            batch, offset = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=query_filter,
                limit=1000,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in batch:
                stored_sha = point.payload.get("sha", "")
                if stored_sha.startswith(sha):
                    return point.payload
            if offset is None:
                break
        return None

    async def get_commits_without_diffs(self, service: str) -> list[str]:
        shas: list[str] = []
        offset = None
        while True:
            results, offset = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(key="service", match=MatchValue(value=service)),
                    ],
                    must_not=[
                        FieldCondition(key="has_diff", match=MatchValue(value=True)),
                    ],
                ),
                limit=1000,
                offset=offset,
                with_payload=["sha"],
                with_vectors=False,
            )
            for point in results:
                sha = point.payload.get("sha")
                if sha:
                    shas.append(sha)
            if offset is None:
                break
        return shas

    async def update_commit_diffs(
        self,
        service: str,
        payloads: list[dict[str, Any]],
    ) -> None:
        async def _update_one(p: dict[str, Any]) -> None:
            point_id = _commit_point_id(service, p["sha"])
            await self._client.set_payload(
                collection_name=self._collection,
                payload={
                    "files": p.get("files", []),
                    "has_diff": p.get("has_diff", False),
                    "diff_truncated": p.get("diff_truncated", False),
                },
                points=[point_id],
            )

        await asyncio.gather(*(_update_one(p) for p in payloads))

    async def close(self) -> None:
        await self._client.close()
