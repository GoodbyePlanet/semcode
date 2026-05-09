from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from server.embeddings.factory import get_embedding_provider
from server.indexer.git_history import GitHistoryPipeline
from server.state import get_commit_store


def register_history_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def search_commits(
        query: str,
        service: str | None = None,
        limit: int = 10,
    ) -> str:
        """Search git commit history using natural language.

        Args:
            query: Natural language description of what you're looking for in commit history.
            service: Filter by service name
            limit: Maximum number of results (default 10)
        """
        embedder = get_embedding_provider()
        store = get_commit_store()

        query_vector = await embedder.embed_query(query)
        results = await store.search(
            query_vector=query_vector, service=service, limit=limit
        )

        if not results:
            return "No commits found."

        lines = [f"Found {len(results)} commit(s) for: {query!r}\n"]
        for i, hit in enumerate(results, 1):
            p = hit.payload
            sha_short = (p.get("sha") or "")[:8]
            lines.append(f"### {i}. `{sha_short}` — score {hit.score:.3f}")
            lines.append(
                f"**Service**: {p.get('service')} | **Author**: {p.get('author_name')}"
            )
            lines.append(f"**Date**: {p.get('committed_at')}")
            lines.append("")
            lines.append(p.get("message") or "")
            lines.append("")

        return "\n".join(lines)

    @mcp.tool()
    async def get_commit(
        sha: str,
        service: str | None = None,
    ) -> str:
        """Get detailed information about a specific commit including changed files and diffs.

        Args:
            sha: Full commit SHA (as returned by search_commits)
            service: Optional service filter
        """
        store = get_commit_store()
        payload = await store.get_commit_by_sha(sha=sha, service=service)

        if not payload:
            return f"Commit `{sha}` not found in index. Run `index_history` first."

        sha_full = payload.get("sha", sha)
        lines = [
            f"## Commit `{sha_full[:12]}`",
            f"**Service**: {payload.get('service')} | **Author**: {payload.get('author_name')} <{payload.get('author_email')}>",
            f"**Date**: {payload.get('committed_at')}",
            "",
            "### Message",
            payload.get("message") or "",
            "",
        ]

        files = payload.get("files") or []
        if not files:
            lines.append(
                "_No diff data available. Re-run `index_history` to fetch diffs._"
            )
            return "\n".join(lines)

        total_adds = sum(f.get("additions", 0) for f in files)
        total_dels = sum(f.get("deletions", 0) for f in files)
        truncated = payload.get("diff_truncated", False)
        lines.append(
            f"### Changed Files ({len(files)}{'+ more' if truncated else ''}) — +{total_adds} -{total_dels}"
        )
        lines.append("")

        status_icon = {"added": "+", "deleted": "-", "renamed": "~", "modified": "M"}
        for f in files:
            icon = status_icon.get(f.get("status", ""), "?")
            lines.append(
                f"**[{icon}] {f.get('filename')}** (+{f.get('additions', 0)} -{f.get('deletions', 0)})"
            )
            patch = f.get("patch")
            if patch:
                lines.append("```diff")
                lines.append(patch)
                lines.append("```")
            lines.append("")

        if truncated:
            lines.append("_Diff truncated: commit touches more than 50 files._")

        return "\n".join(lines)

    @mcp.tool()
    async def index_history(
        service: str | None = None,
        force: bool = False,
    ) -> str:
        """Index git commit history for one or all services.

        Args:
            service: Name of the service to index. If omitted, all configured services are indexed.
            force: If true, re-index all commits even if already indexed. Defaults to false (incremental).
        """
        store = get_commit_store()
        pipeline = GitHistoryPipeline(store)

        if service:
            result = await pipeline.index_service(service, force=force)
            if "error" in result:
                return f"Service `{service}` not found in config.yaml."
            lines = [
                f"Git history indexed for `{service}`:",
                f"- New commits: {result['new']}",
                f"- Skipped (already indexed): {result.get('skipped', 0)}",
            ]
            if result.get("diff_updated"):
                lines.append(
                    f"- Diffs fetched for existing commits: {result['diff_updated']}"
                )
            return "\n".join(lines)

        results = await pipeline.index_all(force=force)
        lines = ["Git history indexed for all services:\n"]
        total_new = 0
        for svc_name, r in results.items():
            entry = f"- **{svc_name}**: {r.get('new', 0)} new commits ({r.get('skipped', 0)} skipped)"
            if r.get("diff_updated"):
                entry += f", {r['diff_updated']} diffs updated"
            lines.append(entry)
            total_new += r.get("new", 0)
        lines.append(f"\n**Total**: {total_new} new commits")
        return "\n".join(lines)
