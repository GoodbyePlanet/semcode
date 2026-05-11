from __future__ import annotations

import logging

import httpx
from mcp.server.fastmcp import FastMCP

from server.config import settings
from server.embeddings.factory import get_embedding_provider
from server.indexer.github_source import fetch_file_content
from server.state import get_sparse_provider, get_store


logger = logging.getLogger(__name__)


def register_search_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def search_code(
        query: str,
        language: str | None = None,
        service: str | None = None,
        symbol_type: str | None = None,
        limit: int = 10,
    ) -> str:
        """Semantically search code across indexed services using natural language.

        Args:
            query: Natural language description of what you're looking for.
            language: Filter by language: java, python, typescript
            service: Filter by service name
            symbol_type: Filter by type: class, method, interface, enum, record, function,
                         react_component, react_hook, type, pydantic_model
            limit: Maximum number of results (default 10)
        """
        embedder = get_embedding_provider()
        sparse_embedder = get_sparse_provider()
        store = get_store()

        dense_vector = await embedder.embed_query(query)
        sparse_vector = await sparse_embedder.embed_query(query)
        results = await store.search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            limit=limit,
            language=language,
            service=service,
            symbol_type=symbol_type,
        )

        if not results:
            return "No results found."

        lines = [f"Found {len(results)} result(s) for: {query!r}\n"]
        for i, hit in enumerate(results, 1):
            p = hit.payload
            score = f"{hit.score:.3f}"
            loc = f"{p.get('file_path', '?')}:{p.get('start_line', '?')}-{p.get('end_line', '?')}"
            ann = ", ".join(p.get("annotations") or [])
            lines.append(
                f"### {i}. `{p.get('symbol_name')}` ({p.get('symbol_type')}) — score {score}"
            )
            lines.append(f"**Location**: `{loc}`")
            lines.append(
                f"**Service**: {p.get('service')} | **Language**: {p.get('language')}"
            )
            if ann:
                lines.append(f"**Annotations**: {ann}")
            if p.get("http_route"):
                lines.append(f"**Route**: {p.get('http_method')} {p.get('http_route')}")
            lines.append("")
            lines.append("```" + (p.get("language") or ""))
            lines.append((p.get("signature") or p.get("source") or "")[:500])
            lines.append("```")
            lines.append("")

        return "\n".join(lines)

    @mcp.tool()
    async def find_symbol(
        name: str,
        symbol_type: str | None = None,
        service: str | None = None,
        exact: bool = False,
    ) -> str:
        """Find a class, method, interface, or function by name.

        Args:
            name: Symbol name to search for
            symbol_type: Optional type filter: class, method, interface, enum, record, function, etc.
            service: Optional service filter
            exact: If true, only exact name matches. If false (default), partial/fuzzy matching.
        """
        store = get_store()
        results = await store.find_by_name(
            name=name, symbol_type=symbol_type, service=service, exact=exact
        )

        if not results:
            return f"No symbol found matching `{name}`."

        lines = [f"Found {len(results)} symbol(s) matching `{name}`:\n"]
        for point in results:
            p = point.payload
            loc = f"{p.get('file_path', '?')}:{p.get('start_line', '?')}-{p.get('end_line', '?')}"
            lines.append(f"### `{p.get('symbol_name')}` ({p.get('symbol_type')})")
            lines.append(f"**Location**: `{loc}`")
            lines.append(
                f"**Service**: {p.get('service')} | **Package**: {p.get('package', 'N/A')}"
            )
            if p.get("parent_name"):
                lines.append(f"**Parent**: `{p.get('parent_name')}`")
            lines.append("")
            lines.append("```" + (p.get("language") or ""))
            lines.append((p.get("source") or "")[:800])
            lines.append("```")
            lines.append("")

        return "\n".join(lines)

    @mcp.tool()
    async def find_usages(
        symbol_name: str,
        service: str | None = None,
        limit: int = 10,
    ) -> str:
        """Find code that references or uses a specific symbol name.

        Args:
            symbol_name: The symbol to find references to (e.g. "ProductService", "PlaceOrderRequest")
            service: Optional service filter
            limit: Maximum number of results (default 10)
        """
        embedder = get_embedding_provider()
        sparse_embedder = get_sparse_provider()
        store = get_store()

        query = f"code that uses or references {symbol_name}"
        dense_vector = await embedder.embed_query(query)
        sparse_vector = await sparse_embedder.embed_query(query)
        results = await store.search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            limit=limit,
            service=service,
        )

        filtered = [r for r in results if r.payload.get("symbol_name") != symbol_name][
            :limit
        ]

        if not filtered:
            return f"No usages of `{symbol_name}` found."

        lines = [f"Found {len(filtered)} usage(s) of `{symbol_name}`:\n"]
        for i, hit in enumerate(filtered, 1):
            p = hit.payload
            loc = f"{p.get('file_path', '?')}:{p.get('start_line', '?')}"
            lines.append(f"### {i}. `{p.get('symbol_name')}` in `{p.get('file_path')}`")
            lines.append(f"**Location**: `{loc}` | **Service**: {p.get('service')}")
            lines.append("")
            # Show relevant snippet around the symbol name
            source = p.get("source") or ""
            idx = source.find(symbol_name)
            if idx >= 0:
                start = max(0, idx - 100)
                end = min(len(source), idx + len(symbol_name) + 200)
                snippet = source[start:end]
                lines.append("```" + (p.get("language") or ""))
                lines.append(snippet)
                lines.append("```")
            lines.append("")

        return "\n".join(lines)

    @mcp.tool()
    async def get_code_context(
        file_path: str,
        symbol_name: str | None = None,
    ) -> str:
        """Get the full source code of a file or a specific symbol within it.

        Args:
            file_path: Relative file path as shown in search results
            symbol_name: Optional symbol name to retrieve a specific class/method
        """
        store = get_store()

        # Resolve service from the index to find the correct repo and ref
        file_info = await store.get_file_info(file_path)
        if not file_info:
            return f"File not found in index: `{file_path}`"

        service_name = file_info["service"]
        services = settings.load_services()
        svc = next((s for s in services if s.name == service_name), None)
        if not svc:
            return f"Service `{service_name}` is no longer in config.yaml."

        # Strip the "{service_name}/" prefix, then restore the root prefix so the
        # path matches the actual location in the GitHub repo tree.
        rel_path = file_path[len(svc.name) + 1 :]
        path_in_repo = f"{svc.root.rstrip('/')}/{rel_path}" if svc.root else rel_path
        try:
            raw = await fetch_file_content(
                settings.github_token, svc.github_repo, path_in_repo, svc.github_ref
            )
            content = raw.decode("utf-8", errors="replace")
        except httpx.HTTPError as exc:
            logger.exception(
                "Failed to fetch %s from GitHub (%s)", file_path, svc.github_repo
            )
            return (
                f"Failed to fetch `{file_path}` from GitHub ({svc.github_repo}): {exc}"
            )

        if symbol_name is None:
            return f"```\n{content}\n```"

        # Find the symbol in Qdrant for precise line numbers
        results = await store.find_by_name(name=symbol_name, exact=True)
        matched = [r for r in results if r.payload.get("file_path") == file_path]

        if matched:
            p = matched[0].payload
            start = max(0, (p.get("start_line") or 1) - 1)
            end = p.get("end_line") or len(content.splitlines())
            lines = content.splitlines()
            snippet = "\n".join(lines[start:end])
            return (
                f"**{symbol_name}** ({p.get('symbol_type')}) "
                f"at `{file_path}`:{start + 1}-{end}\n\n"
                f"```{p.get('language', '')}\n{snippet}\n```"
            )

        # Fallback: text search for symbol name in file
        for i, line in enumerate(content.splitlines(), 1):
            if symbol_name in line:
                lines = content.splitlines()
                start = max(0, i - 2)
                end = min(len(lines), i + 40)
                snippet = "\n".join(lines[start:end])
                return f"Found `{symbol_name}` near line {i} in `{file_path}`:\n\n```\n{snippet}\n```"

        return f"`{symbol_name}` not found in `{file_path}`."
