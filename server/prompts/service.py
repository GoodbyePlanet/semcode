from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_service_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="service_overview",
        description="Produce an architectural overview of a service: HTTP entry points, main domain types,"
        " architectural layers, and notable framework conventions.",
    )
    def service_overview(service: str) -> str:
        """Architectural overview of a service.

        Args:
            service: Name of the indexed service to summarize (as it appears in `list_indexed_services`).
        """
        return (
            f"Produce a concise architectural overview of the `{service}` service "
            f"using the semcode MCP tools. Work through these steps:\n"
            f"\n"
            f"1. Call `list_indexed_services` to confirm `{service}` is indexed. "
            f"If it is not, stop and tell the user.\n"
            f"\n"
            f"2. Identify HTTP entry points. Call `search_code` with "
            f'`service="{service}"` and try `symbol_type` values appropriate '
            f"to the language: `controller` (Java/Spring), `api_route` (Python/FastAPI), "
            f"or relevant routing symbols for other stacks. Note any HTTP method + path "
            f"on the results.\n"
            f"\n"
            f"3. Identify the main domain types. Call `search_code` with "
            f'`service="{service}"` and `symbol_type` values like `class`, '
            f"`pydantic_model`, `entity`, `record`, `struct`, or `interface`. "
            f"Focus on the central models — skip helpers and DTOs.\n"
            f"\n"
            f"4. Skim the service layer. A short `search_code` query like "
            f'"core business logic" or "main service class" filtered to '
            f'`service="{service}"` usually surfaces the orchestration layer.\n'
            f"\n"
            f"5. **Identify architectural layer boundaries.** For each class or symbol found in "
            f"steps 2-4, assign it to an architectural layer:\n"
            f"   - `api` — controllers, handlers, routes, serializers, views\n"
            f"   - `service` — business logic, use cases, service classes, orchestrators\n"
            f"   - `data` — repositories, DAOs, entities, models, data access objects\n"
            f"   - `config` — configuration classes, settings, feature flags\n"
            f"   - `dto` — request/response objects, mappers, transfer objects\n"
            f"   - `middleware` — interceptors, filters, guards, auth middleware\n"
            f"   - `utility` — shared helpers, common utilities, cross-cutting logic\n"
            f"   Call `find_symbol` or `search_code` with `symbol_type` values like `repository`, "
            f"`entity`, `service`, `config`, `mapper` to confirm which symbols belong to each layer. "
            f"Note which layers import from which — this reveals the service's internal dependency "
            f"direction (e.g., api → service → data is healthy; data → api is a violation).\n"
            f"\n"
            f"Then write the overview with these sections, keeping each tight:\n"
            f"- **Purpose** — 1-2 sentences inferred from entry points and types.\n"
            f"- **HTTP API** — bulleted list of `METHOD /path → Handler.method`.\n"
            f"- **Domain model** — 3-5 bullets on the key types and how they relate.\n"
            f"- **Architectural Layers** — a table: Layer | Key Symbols | Dependencies. "
            f"List which layers exist, which classes/symbols belong to each, and the "
            f"import dependency direction between layers (e.g., `api → service → data`). "
            f"Flag any circular or upside-down dependencies.\n"
            f"- **Notable patterns** — framework conventions worth flagging "
            f"(Spring stereotypes, FastAPI lifecycle hooks, Lombok usage, etc.).\n"
            f"\n"
            f"Skip any section you do not have evidence for. Do not invent details."
        )
