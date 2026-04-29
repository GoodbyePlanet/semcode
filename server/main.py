from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from server.config import settings
from server.state import get_store, set_store
from server.store.qdrant import QdrantStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[None]:
    logger.info("Starting code-search MCP server...")
    store = QdrantStore()
    await store.ensure_collection()
    set_store(store)
    logger.info("Qdrant collection ready. Use the `reindex` MCP tool to index services.")
    yield
    try:
        await get_store().close()
    except RuntimeError:
        pass
    logger.info("code-search MCP server stopped.")


mcp = FastMCP(
    "code-search",
    instructions="Semantic code search across microservices codebases. Supports Go, Java, Python, and TypeScript/React.",
    lifespan=lifespan,
    host=settings.mcp_host,
    port=settings.mcp_port,
)


def main() -> None:
    from server.tools.search import register_search_tools
    from server.tools.index import register_index_tools
    from server.tools.admin import register_admin_tools
    from server.routes.reindex import register_http_routes

    register_search_tools(mcp)
    register_index_tools(mcp)
    register_admin_tools(mcp)
    register_http_routes(mcp)

    mcp.run(transport=settings.mcp_transport)


if __name__ == "__main__":
    main()
