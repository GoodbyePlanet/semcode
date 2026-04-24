from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_index_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def reindex(
        service: str | None = None,
        force: bool = False,
    ) -> str:
        """Trigger reindexing of one or all services.

        Args:
            service: Name of the service to reindex. If omitted, all configured services are reindexed.
            force: If true, re-embed all files even if unchanged. Defaults to false (incremental).
        """
        from server.indexer.pipeline import IndexPipeline
        from server.state import get_store

        store = get_store()
        pipeline = IndexPipeline(store)

        if service:
            result = await pipeline.index_service(service, force=force)
            if "error" in result:
                return f"Service `{service}` not found in config.yaml."
            return (
                f"Reindex complete for `{service}`:\n"
                f"- Files indexed: {result['files']}\n"
                f"- Chunks created: {result['chunks']}\n"
                f"- Files skipped (unchanged): {result.get('skipped', 0)}"
            )
        else:
            results = await pipeline.index_all(force=force)
            lines = ["Reindex complete for all services:\n"]
            total_files = total_chunks = 0
            for svc_name, r in results.items():
                lines.append(
                    f"- **{svc_name}**: {r.get('files', 0)} files, "
                    f"{r.get('chunks', 0)} chunks "
                    f"({r.get('skipped', 0)} skipped)"
                )
                total_files += r.get("files", 0)
                total_chunks += r.get("chunks", 0)
            lines.append(f"\n**Total**: {total_files} files, {total_chunks} chunks")
            return "\n".join(lines)
