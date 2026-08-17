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
    MatchText,
    MatchValue,
    OptimizersConfigDiff,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    ScoredPoint,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    TextIndexParams,
    TextIndexType,
    TokenizerType,
    VectorParams,
)

from server.config import settings

# Payload field holding the tokenized form of symbol_name (original identifier plus
# its camelCase/snake_case subwords). Backed by a full-text index so partial-name
# lookups are served by Qdrant instead of a client-side scan.
SYMBOL_TOKENS_FIELD = "symbol_name_tokens"

FUZZY_MATCH_LIMIT = 50


def _rank_by_name(points: list[ScoredPoint], name: str) -> list[ScoredPoint]:
    """Exact name matches first, then prefix matches, then the rest.

    Qdrant returns scrolled points in point-id order, which would otherwise bury an
    exact hit underneath incidental partial matches.
    """
    name_lower = name.lower()

    def rank(point: ScoredPoint) -> int:
        symbol_name = (point.payload.get("symbol_name") or "").lower()
        if symbol_name == name_lower:
            return 0
        return 1 if symbol_name.startswith(name_lower) else 2

    return sorted(points, key=rank)


def _symbol_point_id(
    service: str, file_path: str, symbol_name: str, start_line: int
) -> str:
    key = f"{service}:{file_path}:{symbol_name}:{start_line}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


class QdrantStore:
    def __init__(self, dimensions: int) -> None:
        self._client = AsyncQdrantClient(url=settings.qdrant_url)
        self._collection = settings.qdrant_collection
        self._dimensions = dimensions

    async def ensure_collection(self) -> None:
        exists = await self._client.collection_exists(self._collection)
        if exists:
            await self._validate_dimensions()
            # Payload indexes are created unconditionally so that indexes added
            # in later versions also reach collections created before them.
            await self._create_payload_indexes()
            return
        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config={
                "text-dense": VectorParams(
                    size=self._dimensions,
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

    async def _validate_dimensions(self) -> None:
        info = await self._client.get_collection(self._collection)
        vectors = info.config.params.vectors
        # Named-vector collections expose a dict; single-vector collections expose VectorParams.
        params = vectors["text-dense"] if isinstance(vectors, dict) else vectors
        actual = params.size
        if actual != self._dimensions:
            raise RuntimeError(
                f"Qdrant collection {self._collection!r} was created with vector size "
                f"{actual}, but the configured embedding provider produces vectors of "
                f"size {self._dimensions}. Either revert EMBEDDINGS_PROVIDER to the "
                "original setting, or drop the collection (this deletes the existing "
                "index) and reindex."
            )

    async def _create_payload_indexes(self) -> None:
        keyword_fields = [
            "language",
            "service",
            "symbol_type",
            "chunk_tier",
            "parent_name",
            "file_path",
            "symbol_name",
        ]
        for field in keyword_fields:
            await self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        # PREFIX tokenizer so a partial query ("Ord") matches a full token ("Order").
        await self._client.create_payload_index(
            collection_name=self._collection,
            field_name=SYMBOL_TOKENS_FIELD,
            field_schema=TextIndexParams(
                type=TextIndexType.TEXT,
                tokenizer=TokenizerType.PREFIX,
                min_token_len=2,
                max_token_len=30,
                lowercase=True,
            ),
        )

    async def upsert_chunks(
        self,
        chunks: list[dict[str, Any]],
        dense_vectors: list[list[float]],
        sparse_vectors: list[SparseVector],
    ) -> list[str]:
        points = []
        point_ids = []
        for chunk, dense, sparse in zip(chunks, dense_vectors, sparse_vectors):
            point_id = _symbol_point_id(
                chunk["service"],
                chunk["file_path"],
                chunk["symbol_name"],
                chunk["start_line"],
            )
            point_ids.append(point_id)
            points.append(
                PointStruct(
                    id=point_id,
                    vector={"text-dense": dense, "text-sparse": sparse},
                    payload=chunk,
                )
            )
        if points:
            await self._client.upsert(collection_name=self._collection, points=points)
        return point_ids

    async def get_point_ids_by_file(self, service: str, file_path: str) -> set[str]:
        """Returns the ids of all points currently stored for this file."""
        ids: set[str] = set()
        offset = None
        scroll_filter = Filter(
            must=[
                FieldCondition(key="service", match=MatchValue(value=service)),
                FieldCondition(key="file_path", match=MatchValue(value=file_path)),
            ]
        )
        while True:
            results, offset = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=scroll_filter,
                limit=1000,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            ids.update(str(point.id) for point in results)
            if offset is None:
                break
        return ids

    async def delete_by_ids(self, point_ids: list[str]) -> None:
        if point_ids:
            await self._client.delete(
                collection_name=self._collection, points_selector=point_ids
            )

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
                    must=[
                        FieldCondition(key="service", match=MatchValue(value=service))
                    ]
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
                must=[
                    FieldCondition(key="file_path", match=MatchValue(value=file_path))
                ]
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
        service: str | None = None,
        chunk_tier: str | None = None,
    ) -> list[ScoredPoint]:
        must = []
        if service:
            must.append(FieldCondition(key="service", match=MatchValue(value=service)))
        if chunk_tier:
            must.append(
                FieldCondition(key="chunk_tier", match=MatchValue(value=chunk_tier))
            )
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
            limit=limit,
            with_payload=True,
        )
        return result.points

    async def find_by_name(
        self,
        name: str,
        symbol_type: str | None = None,
        service: str | None = None,
        chunk_tier: str | None = None,
        exact: bool = False,
    ) -> list[ScoredPoint]:
        must = []
        if exact:
            must.append(FieldCondition(key="symbol_name", match=MatchValue(value=name)))
        if symbol_type:
            must.append(
                FieldCondition(key="symbol_type", match=MatchValue(value=symbol_type))
            )
        if service:
            must.append(FieldCondition(key="service", match=MatchValue(value=service)))
        if chunk_tier:
            must.append(
                FieldCondition(key="chunk_tier", match=MatchValue(value=chunk_tier))
            )

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

        token_filter = Filter(
            must=[
                *must,
                FieldCondition(key=SYMBOL_TOKENS_FIELD, match=MatchText(text=name)),
            ]
        )
        results, _ = await self._client.scroll(
            collection_name=self._collection,
            scroll_filter=token_filter,
            limit=FUZZY_MATCH_LIMIT,
            with_payload=True,
            with_vectors=False,
        )
        matches = list(results)
        if not matches:
            # Two distinct cases reach here, both indistinguishable from an empty
            # MatchText result:
            #   1. The collection predates SYMBOL_TOKENS_FIELD, so the filter runs
            #      against an absent field and matches nothing until a force reindex.
            #   2. A mid-token fragment ("rder", "asskey"). The PREFIX tokenizer only
            #      indexes token *prefixes*, so Qdrant returns nothing for these —
            #      it does not resolve them server-side.
            matches = await self._find_by_name_scanning(name, base_filter)
        return _rank_by_name(matches, name)

    async def _find_by_name_scanning(
        self, name: str, base_filter: Filter | None
    ) -> list[ScoredPoint]:
        """Substring fallback: scrolls the collection and matches in Python.

        Pre-#72 behaviour, retained for collections indexed before
        SYMBOL_TOKENS_FIELD existed and for mid-token fragments, which the
        PREFIX index cannot serve. O(N) in collection size, and unlike the
        indexed path it pages every payload over the wire — measured at 8.8 s
        for a no-match query over 250k symbols, so it is a real cliff on large
        collections, not a rounding error.
        """
        name_lower = name.lower()
        matches: list[ScoredPoint] = []
        offset = None
        while len(matches) < FUZZY_MATCH_LIMIT:
            batch, offset = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=base_filter,
                limit=200,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            matches.extend(
                r
                for r in batch
                if name_lower in (r.payload.get("symbol_name") or "").lower()
            )
            if offset is None:
                break
        return matches

    async def get_service_stats(self) -> list[dict[str, Any]]:
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
                if indexed_at and (
                    services[svc]["last_indexed"] is None
                    or indexed_at > services[svc]["last_indexed"]
                ):
                    services[svc]["last_indexed"] = indexed_at
            if offset is None:
                break

        result = []
        for svc_data in services.values():
            result.append(
                {
                    "service": svc_data["service"],
                    "chunk_count": svc_data["chunk_count"],
                    "file_count": len(svc_data["file_paths"]),
                    "languages": list(svc_data["languages"]),
                    "last_indexed": svc_data["last_indexed"],
                }
            )
        return result

    async def get_indexed_services(self) -> list[str]:
        """Return distinct service names that have indexed code symbols."""
        stats = await self.get_service_stats()
        return sorted(
            s["service"] for s in stats if s["service"] and s["service"] != "unknown"
        )

    async def collection_info(self) -> dict[str, Any]:
        info = await self._client.get_collection(self._collection)
        return {
            "collection": self._collection,
            "total_vectors": info.points_count,
            "status": str(info.status),
            "vector_size": self._dimensions,
        }

    async def close(self) -> None:
        await self._client.close()
