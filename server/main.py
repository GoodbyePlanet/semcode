from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette

from server.config import settings
from server.embeddings import close_embedding_provider, get_embedding_provider
from server.embeddings.bm25 import BM25SparseProvider, close_sparse_embedding_provider
from server.state import (
    get_commit_store,
    get_service_registry,
    get_store,
    set_commit_store,
    set_service_registry,
    set_sparse_provider,
    set_store,
)
from server.store.commit_store import CommitStore
from server.store.qdrant import QdrantStore
from server.store.service_registry import ServiceRegistry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: MCPServer) -> AsyncIterator[None]:
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

    set_service_registry(ServiceRegistry())

    logger.info(
        "Qdrant collections ready. Use `reindex` / `index_history` MCP tools to index services."
    )
    yield
    try:
        await get_store().close()
        await get_commit_store().close()
        await get_service_registry().close()
    except RuntimeError:
        pass
    await close_embedding_provider()
    await close_sparse_embedding_provider()
    logger.info("semcode MCP server stopped.")


# For streamable-http and sse we drive the Starlette app's lifespan ourselves (see main),
# so the per-MCP-session lifespan would re-init the store on every client connect.
_HTTP_TRANSPORTS = {"streamable-http", "sse"}

try:
    # Reported to clients as serverInfo.version; sourced from pyproject so there is
    # no second place to bump. Absent only if the package isn't installed (e.g. a
    # bare source checkout), which must not be fatal at import time.
    _VERSION = version("semcode")
except PackageNotFoundError:  # pragma: no cover
    _VERSION = "0.0.0"

mcp = MCPServer(
    "semcode",
    version=_VERSION,
    instructions=(
        "Semantic code search across microservices codebases. Hybrid retrieval "
        "(dense embeddings + BM25) over symbols parsed with Tree-sitter. Supports "
        "Go, Java, Python, TypeScript/JavaScript (React), Rust, C#, C, C++, Ruby, "
        "PHP, Kotlin, Scala, Swift, Dart, Bash, SQL, Lua, R, Dockerfile, Docker "
        "Compose, Markdown, JSON, HTML, CSS, and XML."
    ),
    lifespan=lifespan if settings.mcp_transport not in _HTTP_TRANSPORTS else None,
)


def _wrap_http_lifespan(app: Starlette) -> None:
    original = app.router.lifespan_context

    @asynccontextmanager
    async def combined(scope_app: Starlette) -> AsyncIterator[None]:
        async with lifespan(mcp), original(scope_app):
            yield

    app.router.lifespan_context = combined


def main() -> None:
    from server.prompts.service import register_service_prompts
    from server.prompts.system import register_system_prompts
    from server.routes.reindex import register_http_routes
    from server.tools.history import register_history_tools
    from server.tools.index import register_index_tools
    from server.tools.search import register_search_tools
    from server.tools.stats import register_stats_tools

    register_search_tools(mcp)
    register_index_tools(mcp)
    register_stats_tools(mcp)
    register_history_tools(mcp)
    register_service_prompts(mcp)
    register_system_prompts(mcp)
    register_http_routes(mcp)

    if settings.mcp_transport in _HTTP_TRANSPORTS:
        # `host` must match the bind address: the app factories auto-enable DNS
        # rebinding protection (allowed_hosts = localhost only) when host is a
        # loopback address, which would reject container traffic on 0.0.0.0.
        app = (
            mcp.streamable_http_app(host=settings.mcp_host)
            if settings.mcp_transport == "streamable-http"
            else mcp.sse_app(host=settings.mcp_host)
        )
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
