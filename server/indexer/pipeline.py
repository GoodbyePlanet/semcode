from __future__ import annotations

import logging
import re
import textwrap
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from server.config import settings
from server.embeddings.base import EmbeddingProvider
from server.embeddings.bm25 import BM25SparseProvider, get_sparse_embedding_provider
from server.embeddings.factory import get_embedding_provider
from server.indexer.github_source import fetch_blob_content, list_github_files
from server.parser.base import CodeSymbol
from server.parser.registry import parse_file
from server.store.qdrant import QdrantStore

logger = logging.getLogger(__name__)

_MAX_EMBEDDING_CHARS = 6000  # ~1500 tokens


@dataclass
class ProgressEvent:
    phase: str  # "discovery" | "upserting" | "cleanup"
    current: int
    total: int
    percentage: float
    service: str


def _build_embedding_text(symbol: CodeSymbol, service_name: str) -> str:
    lines = []

    lang_display = {"java": "Java", "python": "Python", "typescript": "TypeScript"}.get(
        symbol.language, symbol.language
    )
    type_display = symbol.symbol_type.replace("_", " ")
    preamble = f"{lang_display} {type_display} `{symbol.name}`"
    if symbol.parent_name:
        preamble += f" in class `{symbol.parent_name}`"
    preamble += f" (service: {service_name})"
    lines.append(preamble)

    if symbol.package:
        lines.append(f"Package/module: {symbol.package}")

    extras = symbol.extras or {}

    if stereotype := extras.get("spring_stereotype"):
        lines.append(f"Spring stereotype: {stereotype}")

    if http_method := extras.get("http_method"):
        route = extras.get("http_route") or ""
        lines.append(f"HTTP endpoint: {http_method} {route}")

    if symbol.annotations:
        ann_str = ", ".join(
            f"@{a}" if not a.startswith("@") else a for a in symbol.annotations[:8]
        )
        lines.append(f"Annotations: {ann_str}")

    if lombok := extras.get("lombok_annotations"):
        lines.append(f"Lombok: {', '.join(lombok)}")

    if extras.get("uses_memo"):
        lines.append("Wrapped in React.memo for performance.")

    if symbol.docstring:
        raw = symbol.docstring.strip()
        doc = re.sub(r'^("""|\'\'\'|/\*\*?)\s*', "", raw)
        doc = re.sub(r'\s*("""|\'\'\'|\*/)$', "", doc)
        doc = textwrap.dedent(doc).strip()
        if doc:
            lines.append(doc[:300])

    lines.append("")

    if symbol.signature:
        lines.append(symbol.signature)

    source = symbol.source or ""
    if len(source) > _MAX_EMBEDDING_CHARS:
        source = source[:_MAX_EMBEDDING_CHARS] + "\n// ... (truncated)"
    lines.append(source)

    return "\n".join(lines)


def _build_bm25_text(symbol: CodeSymbol) -> str:
    parts = []
    if symbol.signature:
        parts.append(symbol.signature)
    if symbol.docstring:
        parts.append(symbol.docstring)
    parts.append(symbol.source or "")
    return "\n".join(parts)


def _symbol_to_payload(
    symbol: CodeSymbol, service_name: str, file_hash_val: str
) -> dict[str, Any]:
    return {
        "symbol_name": symbol.name,
        "symbol_type": symbol.symbol_type,
        "language": symbol.language,
        "service": service_name,
        "file_path": symbol.file_path,
        "package": symbol.package,
        "parent_name": symbol.parent_name,
        "annotations": symbol.annotations,
        "signature": symbol.signature,
        "start_line": symbol.start_line,
        "end_line": symbol.end_line,
        "source": symbol.source,
        "chunk_tier": "method" if symbol.parent_name else "class",
        "docstring": symbol.docstring,
        "file_hash": file_hash_val,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        **{k: v for k, v in (symbol.extras or {}).items() if v is not None},
    }


class IndexPipeline:
    def __init__(self, store: QdrantStore) -> None:
        self._store = store
        self._embedder: EmbeddingProvider = get_embedding_provider()
        self._sparse_embedder: BM25SparseProvider = get_sparse_embedding_provider()

    async def index_service(
        self,
        service_name: str,
        force: bool = False,
        progress_callback: Callable[[ProgressEvent], Awaitable[None]] | None = None,
    ) -> dict[str, int]:
        await self._store.ensure_collection()
        services = settings.load_services()
        svc = next((s for s in services if s.name == service_name), None)
        if svc is None:
            return {"error": 1, "files": 0, "chunks": 0}

        async with httpx.AsyncClient() as http_client:
            github_files = await list_github_files(
                settings.github_token,
                svc.github_repo,
                svc.github_ref,
                svc.name,
                svc.exclude,
                svc.root,
                client=http_client,
            )

            if progress_callback:
                await progress_callback(
                    ProgressEvent(
                        phase="discovery",
                        current=len(github_files),
                        total=len(github_files),
                        percentage=100.0,
                        service=service_name,
                    )
                )

            existing_hashes = await self._store.get_indexed_file_hashes(svc.name)

            indexed_files = 0
            total_chunks = 0
            skipped = 0
            total_files = len(github_files)

            for i, f in enumerate(github_files):
                # "{service_name}/{path_in_repo}" — consistent path format across all tools
                stored_path = f"{svc.name}/{f.rel_path}"

                # blob_sha IS the content fingerprint — no download needed to detect unchanged files
                if not force and existing_hashes.get(stored_path) == f.blob_sha:
                    skipped += 1
                    continue

                try:
                    content = await fetch_blob_content(
                        settings.github_token,
                        svc.github_repo,
                        f.blob_sha,
                        client=http_client,
                    )
                except Exception as exc:
                    logger.error("Failed to fetch %s: %s", stored_path, exc)
                    continue

                symbols = parse_file(content, stored_path)
                if not symbols:
                    # File has no indexable symbols; clean up any stale entries.
                    await self._store.delete_by_file(svc.name, stored_path)
                    continue

                texts_dense = [_build_embedding_text(s, svc.name) for s in symbols]
                texts_sparse = [_build_bm25_text(s) for s in symbols]
                try:
                    dense_vectors = await self._embedder.embed_batch(texts_dense)
                    sparse_vectors = await self._sparse_embedder.embed_batch(
                        texts_sparse
                    )
                except Exception as exc:
                    logger.error("Embedding failed for %s: %s", stored_path, exc)
                    continue  # keep existing index entries until embedding succeeds

                payloads = [
                    _symbol_to_payload(s, svc.name, f.blob_sha) for s in symbols
                ]
                await self._store.delete_by_file(svc.name, stored_path)
                await self._store.upsert_chunks(payloads, dense_vectors, sparse_vectors)

                indexed_files += 1
                total_chunks += len(symbols)
                logger.info("Indexed %s: %d symbols", stored_path, len(symbols))

                if progress_callback:
                    await progress_callback(
                        ProgressEvent(
                            phase="upserting",
                            current=i + 1,
                            total=total_files,
                            percentage=round((i + 1) / max(total_files, 1) * 100, 1),
                            service=service_name,
                        )
                    )

        all_stored_paths = {f"{svc.name}/{f.rel_path}" for f in github_files}
        stale_paths = [p for p in existing_hashes if p not in all_stored_paths]
        for stale_path in stale_paths:
            await self._store.delete_by_file(svc.name, stale_path)
            logger.info("Removed stale file from index: %s", stale_path)

        if progress_callback and stale_paths:
            await progress_callback(
                ProgressEvent(
                    phase="cleanup",
                    current=len(stale_paths),
                    total=len(stale_paths),
                    percentage=100.0,
                    service=service_name,
                )
            )

        return {"files": indexed_files, "chunks": total_chunks, "skipped": skipped}

    async def index_all(
        self,
        force: bool = False,
        progress_callback: Callable[[ProgressEvent], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        services = settings.load_services()
        results: dict[str, Any] = {}
        for svc in services:
            logger.info("Indexing service: %s", svc.name)
            results[svc.name] = await self.index_service(
                svc.name, force=force, progress_callback=progress_callback
            )
        return results
