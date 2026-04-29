from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from server.indexer.pipeline import IndexPipeline
from server.state import get_store


def register_http_routes(mcp: FastMCP) -> None:

    @mcp.custom_route("/reindex", methods=["POST"])
    async def reindex(request: Request) -> JSONResponse:
        """POST /reindex — trigger reindexing of one or all services.

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

        if service:
            result = await pipeline.index_service(service, force=force)
        else:
            result = await pipeline.index_all(force=force)

        return JSONResponse(result)
