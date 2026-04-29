from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from server.config import settings
from server.state import get_store


logger = logging.getLogger(__name__)


def register_admin_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def list_indexed_services() -> str:
        """List all indexed services with file counts, chunk counts, languages, and last indexed time."""
        store = get_store()
        services = await store.get_service_stats()

        if not services:
            return "No services indexed yet. Use `reindex` to index services."

        lines = [f"**{len(services)} service(s) indexed:**\n"]
        for svc in sorted(services, key=lambda s: s["service"]):
            lines.append(f"### {svc['service']}")
            lines.append(f"- Chunks: {svc['chunk_count']}")
            lines.append(f"- Files: {svc['file_count']}")
            lines.append(f"- Languages: {', '.join(svc['languages'])}")
            lines.append(f"- Last indexed: {svc.get('last_indexed', 'unknown')}")
            lines.append("")

        return "\n".join(lines)

    @mcp.tool()
    async def index_stats() -> str:
        """Show Qdrant collection statistics and configured services."""
        store = get_store()

        try:
            info = await store.collection_info()
        except Exception as exc:
            logger.exception("Failed to reach Qdrant")
            return f"Could not reach Qdrant: {exc}"

        configured = settings.load_services()

        lines = [
            "## Code Search Index Stats\n",
            f"**Collection**: `{info['collection']}`",
            f"**Total vectors**: {info['total_vectors']}",
            f"**Vector dimensions**: {info['vector_size']}",
            f"**Status**: {info['status']}",
            "",
            f"**Configured services** ({len(configured)}):",
        ]
        for svc in configured:
            lines.append(f"- `{svc.name}` — `{svc.github_repo}@{svc.github_ref}`")

        lines.append("")
        lines.append(f"**Embeddings URL**: {settings.embeddings_url}")

        return "\n".join(lines)
