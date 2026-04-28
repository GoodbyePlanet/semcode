from __future__ import annotations

import logging
import re
import textwrap
from datetime import datetime, timezone
from typing import Any

from server.config import ServiceConfig, settings
from server.embeddings.jina import get_embedding_provider
from server.indexer.github_source import fetch_blob_content, list_github_files
from server.parser.base import CodeSymbol
from server.parser.registry import parse_file
from server.store.qdrant import QdrantStore

logger = logging.getLogger(__name__)

_MAX_EMBEDDING_CHARS = 6000  # ~1500 tokens


def _build_embedding_text(symbol: CodeSymbol, service_name: str) -> str:
    lines = []

    lang_display = {"java": "Java", "python": "Python", "typescript": "TypeScript"}.get(
        symbol.language, symbol.language
    )
    type_display = symbol.symbol_type.replace("_", " ")
    preamble = f"{lang_display} {type_display} `{symbol.name}`"
    if symbol.parent_name:
        preamble += f" in {symbol.symbol_type == 'method' and 'class' or 'module'} `{symbol.parent_name}`"
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
        ann_str = ", ".join(f"@{a}" if not a.startswith("@") else a for a in symbol.annotations[:8])
        lines.append(f"Annotations: {ann_str}")

    if lombok := extras.get("lombok_annotations"):
        lines.append(f"Lombok: {', '.join(lombok)}")

    if extras.get("uses_memo"):
        lines.append("Wrapped in React.memo for performance.")

    if symbol.docstring:
        raw = symbol.docstring.strip()
        doc = re.sub(r'^("""|\'\'\'|/\*\*?)\s*', '', raw)
        doc = re.sub(r'\s*("""|\'\'\'|\*/)$', '', doc)
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
        self._embedder = get_embedding_provider()

    async def index_service(self, service_name: str, force: bool = False) -> dict[str, int]:
        services = settings.load_services()
        svc = next((s for s in services if s.name == service_name), None)
        if svc is None:
            return {"error": 1, "files": 0, "chunks": 0}

        github_files = await list_github_files(
            settings.github_token, svc.github_repo, svc.github_ref,
            svc.name, svc.exclude, svc.root,
        )

        existing_hashes = {} if force else await self._store.get_indexed_file_hashes(svc.name)

        indexed_files = 0
        total_chunks = 0
        skipped = 0

        for f in github_files:
            # "{service_name}/{path_in_repo}" — consistent path format across all tools
            stored_path = f"{svc.name}/{f.rel_path}"

            # blob_sha IS the content fingerprint — no download needed to detect unchanged files
            if not force and existing_hashes.get(stored_path) == f.blob_sha:
                skipped += 1
                continue

            try:
                content = await fetch_blob_content(settings.github_token, svc.github_repo, f.blob_sha)
            except Exception as exc:
                logger.error("Failed to fetch %s: %s", stored_path, exc)
                continue

            await self._store.delete_by_file(svc.name, stored_path)
            symbols = parse_file(content, stored_path)
            if not symbols:
                continue

            texts = [_build_embedding_text(s, svc.name) for s in symbols]
            try:
                vectors = await self._embedder.embed_batch(texts)
            except Exception as exc:
                logger.error("Embedding failed for %s: %s", stored_path, exc)
                continue

            payloads = [_symbol_to_payload(s, svc.name, f.blob_sha) for s in symbols]
            await self._store.upsert_chunks(payloads, vectors)

            indexed_files += 1
            total_chunks += len(symbols)
            logger.info("Indexed %s: %d symbols", stored_path, len(symbols))

        all_stored_paths = {f"{svc.name}/{f.rel_path}" for f in github_files}
        for stale_path in existing_hashes:
            if stale_path not in all_stored_paths:
                await self._store.delete_by_file(svc.name, stale_path)
                logger.info("Removed stale file from index: %s", stale_path)

        return {"files": indexed_files, "chunks": total_chunks, "skipped": skipped}

    async def index_all(self, force: bool = False) -> dict[str, Any]:
        services = settings.load_services()
        results: dict[str, Any] = {}
        for svc in services:
            logger.info("Indexing service: %s", svc.name)
            results[svc.name] = await self.index_service(svc.name, force=force)
        return results
