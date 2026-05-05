from __future__ import annotations

import asyncio
import dataclasses
import json
import logging

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import StreamingResponse

from server.indexer.git_history import GitHistoryPipeline
from server.indexer.pipeline import IndexPipeline, ProgressEvent
from server.state import get_commit_store, get_store

logger = logging.getLogger(__name__)


def register_http_routes(mcp: FastMCP) -> None:

    @mcp.custom_route("/reindex", methods=["POST"])
    async def reindex(request: Request) -> StreamingResponse:
        """POST /reindex/stream — streaming variant of /reindex, returns NDJSON.

        Emits progress frames while indexing, followed by a final summary frame:
            {"type": "progress", "phase": "discovery"|"upserting"|"cleanup",
             "current": int, "total": int, "percentage": float, "service": str}
            {"type": "done", "result": {"files": int, "chunks": int, "skipped": int}}

        Body (optional JSON):
            service: str  — service name; omit to reindex all
            force: bool   — re-embed unchanged files (default false)
        """
        body: dict = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()

        service: str | None = body.get("service")
        force: bool = bool(body.get("force", False))

        pipeline = IndexPipeline(get_store())
        logger.info("Reindex/stream started: service=%s force=%s", service or "ALL", force)

        async def generate():
            queue: asyncio.Queue = asyncio.Queue()

            async def callback(event: ProgressEvent) -> None:
                await queue.put(event)

            async def run() -> None:
                try:
                    if service:
                        result = await pipeline.index_service(service, force=force, progress_callback=callback)
                    else:
                        result = await pipeline.index_all(force=force, progress_callback=callback)
                    await queue.put({"__done__": True, "result": result})
                except Exception as exc:
                    await queue.put(exc)

            task = asyncio.create_task(run())
            try:
                while True:
                    item = await queue.get()
                    if isinstance(item, Exception):
                        yield json.dumps({"type": "error", "message": str(item)}) + "\n"
                        break
                    if isinstance(item, dict):
                        yield json.dumps({"type": "done", "result": item["result"]}) + "\n"
                        break
                    yield json.dumps({"type": "progress", **dataclasses.asdict(item)}) + "\n"
            finally:
                await task

        return StreamingResponse(generate(), media_type="application/x-ndjson")

    @mcp.custom_route("/reindex-history", methods=["POST"])
    async def reindex_history(request: Request) -> StreamingResponse:
        """POST /reindex-history/stream — streaming variant of /reindex-history, returns NDJSON.

        Emits progress frames while indexing, followed by a final summary frame:
            {"type": "progress", "phase": "discovery"|"embedding"|"upserting",
             "current": int, "total": int, "percentage": float, "service": str}
            {"type": "done", "result": {"new": int, "skipped": int, "diff_updated": int}}

        Body (optional JSON):
            service: str  — service name; omit to index all
            force: bool   — re-index already indexed commits (default false)
        """
        body: dict = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()

        service: str | None = body.get("service")
        force: bool = bool(body.get("force", False))

        pipeline = GitHistoryPipeline(get_commit_store())
        logger.info("Reindex-history/stream started: service=%s force=%s", service or "ALL", force)

        async def generate():
            queue: asyncio.Queue = asyncio.Queue()

            async def callback(event: ProgressEvent) -> None:
                await queue.put(event)

            async def run() -> None:
                try:
                    if service:
                        result = await pipeline.index_service(service, force=force, progress_callback=callback)
                    else:
                        result = await pipeline.index_all(force=force, progress_callback=callback)
                    await queue.put({"__done__": True, "result": result})
                except Exception as exc:
                    await queue.put(exc)

            task = asyncio.create_task(run())
            try:
                while True:
                    item = await queue.get()
                    if isinstance(item, Exception):
                        yield json.dumps({"type": "error", "message": str(item)}) + "\n"
                        break
                    if isinstance(item, dict):
                        yield json.dumps({"type": "done", "result": item["result"]}) + "\n"
                        break
                    yield json.dumps({"type": "progress", **dataclasses.asdict(item)}) + "\n"
            finally:
                await task

        return StreamingResponse(generate(), media_type="application/x-ndjson")
