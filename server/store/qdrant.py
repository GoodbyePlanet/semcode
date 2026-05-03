from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    HnswConfigDiff,
    MatchValue,
    OptimizersConfigDiff,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    ScoredPoint,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from server.config import settings


def _symbol_point_id(service: str, file_path: str, symbol_name: str, start_line: int) -> str:
    key = f"{service}:{file_path}:{symbol_name}:{start_line}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


class QdrantStore:
    def __init__(self) -> None:
        self._client = AsyncQdrantClient(url=settings.qdrant_url)
        self._collection = settings.qdrant_collection

    async def ensure_collection(self) -> None:
        exists = await self._client.collection_exists(self._collection)
        if not exists:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config={
                    "text-dense": VectorParams(
                        size=settings.embeddings_dimensions,
                        distance=Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    "text-sparse": SparseVectorParams(
                        index=SparseIndexParams(on_disk=False),
                    ),
                },
                optimizers_config=OptimizersConfigDiff(indexing_threshold=500),
                hnsw_config=HnswConfigDiff(m=16, ef_construct=128),
            )
            await self._create_payload_indexes()

    async def _create_payload_indexes(self) -> None:
        keyword_fields = [
            "language",
            "service",
            "symbol_type",
            "chunk_tier",
            "parent_name",
            "file_path",
        ]
        for field in keyword_fields:
            await self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )

    async def upsert_chunks(
        self,
        chunks: list[dict[str, Any]],
        dense_vectors: list[list[float]],
        sparse_vectors: list[SparseVector],
    ) -> None:
        points = []
        for chunk, dense, sparse in zip(chunks, dense_vectors, sparse_vectors):
            point_id = _symbol_point_id(
                chunk["service"],
                chunk["file_path"],
                chunk["symbol_name"],
                chunk["start_line"],
            )
            points.append(
                PointStruct(
                    id=point_id,
                    vector={"text-dense": dense, "text-sparse": sparse},
                    payload=chunk,
                )
            )
        if points:
            await self._client.upsert(collection_name=self._collection, points=points)

    async def delete_by_file(self, service: str, file_path: str) -> None:
        await self._client.delete(
            collection_name=self._collection,
            points_selector=Filter(
                must=[
                    FieldCondition(key="service", match=MatchValue(value=service)),
                    FieldCondition(key="file_path", match=MatchValue(value=file_path)),
                ]
            ),
        )

    async def delete_by_service(self, service: str) -> None:
        await self._client.delete(
            collection_name=self._collection,
            points_selector=Filter(
                must=[FieldCondition(key="service", match=MatchValue(value=service))]
            ),
        )

    async def get_indexed_file_hashes(self, service: str) -> dict[str, str]:
        """Returns {file_path: file_hash} for all chunks of a service."""
        hashes: dict[str, str] = {}
        offset = None
        while True:
            results, offset = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="service", match=MatchValue(value=service))]
                ),
                limit=1000,
                offset=offset,
                with_payload=["file_path", "file_hash"],
                with_vectors=False,
            )
            for point in results:
                fp = point.payload.get("file_path")
                fh = point.payload.get("file_hash")
                if fp and fh:
                    hashes[fp] = fh
            if offset is None:
                break
        return hashes

    async def get_file_info(self, file_path: str) -> dict[str, Any] | None:
        """Return {service, file_hash} for the first indexed point at file_path."""
        results, _ = await self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="file_path", match=MatchValue(value=file_path))]
            ),
            limit=1,
            with_payload=["service", "file_hash"],
            with_vectors=False,
        )
        return results[0].payload if results else None

    async def search(
        self,
        dense_vector: list[float],
        sparse_vector: SparseVector,
        limit: int = 10,
        language: str | None = None,
        service: str | None = None,
        symbol_type: str | None = None,
    ) -> list[ScoredPoint]:
        must = []
        if language:
            must.append(FieldCondition(key="language", match=MatchValue(value=language)))
        if service:
            must.append(FieldCondition(key="service", match=MatchValue(value=service)))
        if symbol_type:
            must.append(FieldCondition(key="symbol_type", match=MatchValue(value=symbol_type)))

        query_filter = Filter(must=must) if must else None

        result = await self._client.query_points(
            collection_name=self._collection,
            prefetch=[
                Prefetch(
                    query=dense_vector,
                    using="text-dense",
                    limit=limit * 2,
                    filter=query_filter,
                ),
                Prefetch(
                    query=sparse_vector,
                    using="text-sparse",
                    limit=limit * 2,
                    filter=query_filter,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return result.points

    async def find_by_name(
        self,
        name: str,
        symbol_type: str | None = None,
        service: str | None = None,
        exact: bool = False,
    ) -> list[ScoredPoint]:
        must = []
        if exact:
            must.append(FieldCondition(key="symbol_name", match=MatchValue(value=name)))
        if symbol_type:
            must.append(FieldCondition(key="symbol_type", match=MatchValue(value=symbol_type)))
        if service:
            must.append(FieldCondition(key="service", match=MatchValue(value=service)))

        base_filter = Filter(must=must) if must else None

        if exact:
            results, _ = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=base_filter,
                limit=20,
                with_payload=True,
                with_vectors=False,
            )
            return list(results)

        name_lower = name.lower()
        matches: list[ScoredPoint] = []
        offset = None
        while len(matches) < 50:
            batch, offset = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=base_filter,
                limit=200,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for r in batch:
                if name_lower in (r.payload.get("symbol_name") or "").lower():
                    matches.append(r)
            if offset is None:
                break
        return matches

    async def get_service_stats(self) -> list[dict[str, Any]]:
        info = await self._client.get_collection(self._collection)
        total = info.points_count

        services: dict[str, dict] = {}
        offset = None
        while True:
            results, offset = await self._client.scroll(
                collection_name=self._collection,
                limit=1000,
                offset=offset,
                with_payload=["service", "language", "file_path", "indexed_at"],
                with_vectors=False,
            )
            for point in results:
                svc = point.payload.get("service", "unknown")
                if svc not in services:
                    services[svc] = {
                        "service": svc,
                        "chunk_count": 0,
                        "file_paths": set(),
                        "languages": set(),
                        "last_indexed": None,
                    }
                services[svc]["chunk_count"] += 1
                services[svc]["file_paths"].add(point.payload.get("file_path", ""))
                services[svc]["languages"].add(point.payload.get("language", ""))
                indexed_at = point.payload.get("indexed_at")
                if indexed_at:
                    if services[svc]["last_indexed"] is None or indexed_at > services[svc]["last_indexed"]:
                        services[svc]["last_indexed"] = indexed_at
            if offset is None:
                break

        result = []
        for svc_data in services.values():
            result.append({
                "service": svc_data["service"],
                "chunk_count": svc_data["chunk_count"],
                "file_count": len(svc_data["file_paths"]),
                "languages": list(svc_data["languages"]),
                "last_indexed": svc_data["last_indexed"],
            })
        return result

    async def collection_info(self) -> dict[str, Any]:
        info = await self._client.get_collection(self._collection)
        return {
            "collection": self._collection,
            "total_vectors": info.points_count,
            "status": str(info.status),
            "vector_size": settings.embeddings_dimensions,
        }

    async def close(self) -> None:
        await self._client.close()
