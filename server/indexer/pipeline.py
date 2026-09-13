from __future__ import annotations

import asyncio
import logging
import re
import textwrap
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from qdrant_client.models import SparseVector

from server.config import ServiceConfig, settings
from server.embeddings import get_embedding_provider
from server.embeddings.base import EmbeddingProvider
from server.embeddings.bm25 import BM25SparseProvider, get_sparse_embedding_provider
from server.embeddings.code_tokenizer import symbol_name_tokens
from server.indexer.cleanup import prune_orphaned_services
from server.indexer.github_source import (
    GitHubFile,
    fetch_blob_content,
    list_github_files,
)
from server.parser.base import CodeSymbol, ParseError
from server.parser.registry import parse_file
from server.state import get_reindex_lock, get_service_registry
from server.store.qdrant import SYMBOL_TOKENS_FIELD, QdrantStore
from server.store.service_registry import ServiceRegistry, load_effective_services

logger = logging.getLogger(__name__)

# Bounded fan-out for blob downloads, matching _TREE_WALK_CONCURRENCY /
# _DIFF_CONCURRENCY in github_source.py.
_FETCH_CONCURRENCY = 10
# Parsed files waiting to be embedded. Bounds peak memory and applies
# backpressure to the fetchers while a batch is embedding.
_PARSED_QUEUE_SIZE = 20
# Used when the provider does not declare a batch_size (duck-typed test stubs).
_FALLBACK_EMBED_BATCH_SIZE = 32
# Secondary cut so a batch of unusually large symbols never becomes a giant request.
_MAX_BATCH_CHARS = 400_000


@dataclass(slots=True)
class _ParsedFile:
    stored_path: str
    blob_sha: str
    symbols: list[CodeSymbol]  # empty => drop stale entries, nothing to embed


@dataclass(slots=True)
class _EmbeddedFile:
    parsed: _ParsedFile
    dense: list[list[float]]
    sparse: list[SparseVector]


@dataclass
class ProgressEvent:
    phase: str  # "discovery" | "upserting" | "cleanup"
    current: int
    total: int
    percentage: float
    service: str


def _build_embedding_text(
    symbol: CodeSymbol, service_name: str, max_chars: int | None = None
) -> str:
    if max_chars is None:
        max_chars = settings.embedding_max_chars

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

    # Budget the source against the WHOLE embedding text so the total stays under the
    # model's token limit — the metadata preamble and signature also consume the budget.
    header = "\n".join(lines)
    source = symbol.source or ""
    budget = max(max_chars - len(header) - 1, 0)  # -1 for the newline before source
    if len(source) > budget:
        logger.warning(
            "Truncating embedding source for %s `%s` in %s: %d -> %d chars "
            "(EMBEDDING_MAX_CHARS=%d); the tail is absent from the dense vector.",
            symbol.symbol_type,
            symbol.name,
            symbol.file_path,
            len(source),
            budget,
            max_chars,
        )
        source = source[:budget] + "\n// ... (truncated)"
    lines.append(source)

    return "\n".join(lines)


def _build_bm25_text(symbol: CodeSymbol) -> str:
    extras = symbol.extras or {}
    parts = [symbol.name]
    if symbol.package:
        parts.append(symbol.package)
    if symbol.annotations:
        parts.extend(
            f"@{a}" if not a.startswith("@") else a for a in symbol.annotations
        )
    if http_method := extras.get("http_method"):
        route = extras.get("http_route") or ""
        parts.append(f"{http_method} {route}".strip())
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
        SYMBOL_TOKENS_FIELD: symbol_name_tokens(symbol.name),
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
        "indexed_at": datetime.now(UTC).isoformat(),
        **{k: v for k, v in (symbol.extras or {}).items() if v is not None},
    }


async def _drain_batches(
    queue: asyncio.Queue[_ParsedFile | None], batch_size: int
) -> AsyncIterator[list[_ParsedFile]]:
    """Groups parsed files until their combined symbol count fills a provider batch.

    Terminates on the ``None`` sentinel the producer always sends, flushing
    whatever is still pending. A single file holding more symbols than
    *batch_size* is emitted on its own; ``embed_in_batches`` re-splits it.
    """
    pending: list[_ParsedFile] = []
    pending_symbols = 0
    pending_chars = 0

    while True:
        item = await queue.get()
        if item is None:
            break
        pending.append(item)
        pending_symbols += len(item.symbols)
        pending_chars += sum(len(s.source or "") for s in item.symbols)
        if pending_symbols >= batch_size or pending_chars >= _MAX_BATCH_CHARS:
            yield pending
            pending = []
            pending_symbols = 0
            pending_chars = 0

    if pending:
        yield pending


def _split_by_file(
    files: list[_ParsedFile],
    dense: list[list[float]],
    sparse: list[SparseVector],
) -> list[_EmbeddedFile]:
    """Cuts flat batch vectors back into per-file runs, in the order they were sent."""
    total = sum(len(f.symbols) for f in files)
    if len(dense) != total or len(sparse) != total:
        # Vectors are positional; a miscount would silently attach one symbol's
        # vector to another symbol.
        raise ValueError(
            f"Embedding count mismatch: {len(dense)} dense / {len(sparse)} sparse "
            f"vectors for {total} symbols"
        )

    embedded: list[_EmbeddedFile] = []
    offset = 0
    for f in files:
        end = offset + len(f.symbols)
        embedded.append(_EmbeddedFile(f, dense[offset:end], sparse[offset:end]))
        offset = end
    return embedded


class IndexPipeline:
    def __init__(
        self, store: QdrantStore, registry: ServiceRegistry | None = None
    ) -> None:
        self._store = store
        self._embedder: EmbeddingProvider = get_embedding_provider()
        self._sparse_embedder: BM25SparseProvider = get_sparse_embedding_provider()
        self._registry = registry or get_service_registry()

    async def _produce_parsed_files(
        self,
        svc: ServiceConfig,
        targets: list[tuple[GitHubFile, str]],
        http_client: httpx.AsyncClient,
        queue: asyncio.Queue[_ParsedFile | None],
        on_file_done: Callable[[], None],
    ) -> None:
        """Fetches and parses *targets* concurrently, feeding results to *queue*."""
        sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

        async def _fetch_and_parse(f: GitHubFile, stored_path: str) -> None:
            async with sem:
                try:
                    content = await fetch_blob_content(
                        settings.github_token,
                        svc.github_repo,
                        f.blob_sha,
                        client=http_client,
                    )
                except Exception as exc:  # noqa: BLE001 — keep existing index entries on any fetch failure
                    logger.error("Failed to fetch %s: %s", stored_path, exc)
                    on_file_done()
                    return

                # parse_file stays on the event loop on purpose: registry.py shares one
                # parser instance per language and tree-sitter parsers are not safe for
                # concurrent use, so a thread hop here would be a data race.
                try:
                    symbols = parse_file(content, stored_path)
                except ParseError:
                    logger.error(
                        "Skipping index update for %s: parser failed, "
                        "existing entries preserved",
                        stored_path,
                    )
                    on_file_done()
                    return

            # Queued outside the semaphore so a full queue holds no fetch slot.
            await queue.put(_ParsedFile(stored_path, f.blob_sha, symbols))

        try:
            await asyncio.gather(*[_fetch_and_parse(f, p) for f, p in targets])
        finally:
            # Sentinel, even on cancellation — the consumer must always terminate.
            await queue.put(None)

    async def _embed_files(
        self, files: list[_ParsedFile], service_name: str
    ) -> list[_EmbeddedFile]:
        """Embeds every symbol in *files* as one batch, overlapping dense and sparse."""
        if not files:
            return []

        symbols = [s for f in files for s in f.symbols]
        dense_texts = [_build_embedding_text(s, service_name) for s in symbols]
        sparse_texts = [_build_bm25_text(s) for s in symbols]
        try:
            dense, sparse = await asyncio.gather(
                self._embedder.embed_batch(dense_texts),
                self._sparse_embedder.embed_batch(sparse_texts),
            )
        except Exception as exc:  # noqa: BLE001 — one bad file must not drop the whole batch
            logger.warning(
                "Batch embedding failed for %d files (%s) — retrying file by file",
                len(files),
                exc,
            )
            return await self._embed_files_individually(files, service_name)

        return _split_by_file(files, dense, sparse)

    async def _embed_files_individually(
        self, files: list[_ParsedFile], service_name: str
    ) -> list[_EmbeddedFile]:
        """Per-file retry after a batch failure, so only the bad file is dropped."""
        embedded: list[_EmbeddedFile] = []
        for f in files:
            try:
                dense, sparse = await asyncio.gather(
                    self._embedder.embed_batch(
                        [_build_embedding_text(s, service_name) for s in f.symbols]
                    ),
                    self._sparse_embedder.embed_batch(
                        [_build_bm25_text(s) for s in f.symbols]
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — keep existing index entries until embedding succeeds
                logger.error("Embedding failed for %s: %s", f.stored_path, exc)
                continue
            embedded.append(_EmbeddedFile(f, dense, sparse))
        return embedded

    async def _write_embedded_file(
        self, service_name: str, embedded: _EmbeddedFile
    ) -> int:
        """Upserts one file's symbols and prunes the ids it no longer covers."""
        parsed = embedded.parsed
        payloads = [
            _symbol_to_payload(s, service_name, parsed.blob_sha) for s in parsed.symbols
        ]
        # Upsert new/changed symbols before deleting stale ones, so there's
        # never a window where the file has zero indexed symbols.
        previous_ids = await self._store.get_point_ids_by_file(
            service_name, parsed.stored_path
        )
        new_ids = await self._store.upsert_chunks(
            payloads, embedded.dense, embedded.sparse
        )
        stale_ids = previous_ids - set(new_ids)
        await self._store.delete_by_ids(list(stale_ids))

        logger.info("Indexed %s: %d symbols", parsed.stored_path, len(parsed.symbols))
        return len(parsed.symbols)

    async def index_service(
        self,
        service_name: str,
        force: bool = False,
        progress_callback: Callable[[ProgressEvent], Awaitable[None]] | None = None,
    ) -> dict[str, int]:
        await self._store.ensure_collection()
        services = await load_effective_services(self._registry)
        svc = next((s for s in services if s.name == service_name), None)
        if svc is None:
            return {"error": 1, "files": 0, "chunks": 0}

        async with get_reindex_lock(f"code:{svc.name}"):
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

                total_files = len(github_files)
                # "{service_name}/{path_in_repo}" — consistent path format across all tools.
                # blob_sha IS the content fingerprint — no download needed to detect
                # unchanged files, so they never become fetch targets.
                targets = [
                    (f, path)
                    for f, path in (
                        (f, f"{svc.name}/{f.rel_path}") for f in github_files
                    )
                    if force or existing_hashes.get(path) != f.blob_sha
                ]
                skipped = total_files - len(targets)

                indexed_files = 0
                total_chunks = 0
                # Every file reaches a terminal state exactly once, so this only grows.
                processed = skipped

                def _mark_done() -> None:
                    nonlocal processed
                    processed += 1

                async def _emit_progress() -> None:
                    if progress_callback:
                        await progress_callback(
                            ProgressEvent(
                                phase="upserting",
                                current=processed,
                                total=total_files,
                                percentage=round(
                                    processed / max(total_files, 1) * 100, 1
                                ),
                                service=service_name,
                            )
                        )

                batch_size = getattr(
                    self._embedder, "batch_size", _FALLBACK_EMBED_BATCH_SIZE
                )
                queue: asyncio.Queue[_ParsedFile | None] = asyncio.Queue(
                    maxsize=_PARSED_QUEUE_SIZE
                )
                producer = asyncio.create_task(
                    self._produce_parsed_files(
                        svc, targets, http_client, queue, _mark_done
                    )
                )
                try:
                    async for batch in _drain_batches(queue, batch_size):
                        to_embed = []
                        for parsed in batch:
                            if parsed.symbols:
                                to_embed.append(parsed)
                            else:
                                # No indexable symbols; clean up any stale entries.
                                await self._store.delete_by_file(
                                    svc.name, parsed.stored_path
                                )
                                _mark_done()

                        for embedded in await self._embed_files(to_embed, svc.name):
                            total_chunks += await self._write_embedded_file(
                                svc.name, embedded
                            )
                            indexed_files += 1
                        # Files dropped by an embedding failure are resolved too.
                        processed += len(to_embed)

                        await _emit_progress()

                    await producer
                finally:
                    # Without this an exception in the consumer orphans the producer
                    # inside the http client's context manager.
                    producer.cancel()
                    await asyncio.gather(producer, return_exceptions=True)

                await _emit_progress()

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
        services = await load_effective_services(self._registry)
        await self._store.ensure_collection()
        await prune_orphaned_services(
            self._store, {s.name for s in services}, label="code symbols"
        )

        results: dict[str, Any] = {}
        for svc in services:
            logger.info("Indexing service: %s", svc.name)
            results[svc.name] = await self.index_service(
                svc.name, force=force, progress_callback=progress_callback
            )
        return results
