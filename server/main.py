from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from server.config import settings
from server.embeddings.bm25 import BM25SparseProvider, close_sparse_embedding_provider
from server.embeddings.factory import close_embedding_provider, get_embedding_provider
from server.state import (
    get_commit_store,
    get_store,
    set_commit_store,
    set_sparse_provider,
    set_store,
)
from server.store.commit_store import CommitStore
from server.store.qdrant import QdrantStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[None]:
    logger.info("Starting semcode MCP server...")
    embedder = get_embedding_provider()
    logger.info(
        "Embedding provider: %s (dimensions=%d)",
        settings.embeddings_provider,
        embedder.dimensions,
    )

    store = QdrantStore(dimensions=embedder.dimensions)
    await store.ensure_collection()
    set_store(store)

    commit_store = CommitStore(dimensions=embedder.dimensions)
    await commit_store.ensure_collection()
    set_commit_store(commit_store)

    sparse_provider = BM25SparseProvider()
    set_sparse_provider(sparse_provider)

    logger.info(
        "Qdrant collections ready. Use `reindex` / `index_history` MCP tools to index services."
    )
    yield
    try:
        await get_store().close()
        await get_commit_store().close()
    except RuntimeError:
        pass
    await close_embedding_provider()
    await close_sparse_embedding_provider()
    logger.info("semcode MCP server stopped.")


# For streamable-http we drive the Starlette app's lifespan ourselves (see main),
# so the per-MCP-session lifespan would re-init the store on every client connect.
mcp = FastMCP(
    "semcode",
    instructions="Semantic code search across microservices codebases. Supports Go, Java, Python, and TypeScript/React.",
    lifespan=lifespan if settings.mcp_transport != "streamable-http" else None,
    host=settings.mcp_host,
    port=settings.mcp_port,
)


def _wrap_http_lifespan(app: Starlette) -> None:
    original = app.router.lifespan_context

    @asynccontextmanager
    async def combined(scope_app: Starlette) -> AsyncIterator[None]:
        async with lifespan(mcp):
            async with original(scope_app):
                yield

    app.router.lifespan_context = combined


def main() -> None:
    from server.tools.search import register_search_tools
    from server.tools.index import register_index_tools
    from server.tools.admin import register_admin_tools
    from server.tools.history import register_history_tools
    from server.prompts.service import register_service_prompts
    from server.prompts.system import register_system_prompts
    from server.routes.reindex import register_http_routes

    register_search_tools(mcp)
    register_index_tools(mcp)
    register_admin_tools(mcp)
    register_history_tools(mcp)
    register_service_prompts(mcp)
    register_system_prompts(mcp)
    register_http_routes(mcp)

    if settings.mcp_transport == "streamable-http":
        app = mcp.streamable_http_app()
        _wrap_http_lifespan(app)
        uvicorn.run(
            app,
            host=settings.mcp_host,
            port=settings.mcp_port,
            log_level=mcp.settings.log_level.lower(),
        )
    else:
        mcp.run(transport=settings.mcp_transport)


if __name__ == "__main__":
    main()
