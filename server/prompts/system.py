from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_system_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="system_design_overview",
        description="Produce a complete architectural overview of the whole system: service inventory,"
        " communication topology, shared data stores, and cross-cutting concerns.",
    )
    def system_design_overview() -> str:
        """Complete system design overview across all indexed services."""
        return (
            "Produce a complete system design overview using the semcode MCP tools. "
            "Work through these steps:\n"
            "\n"
            "1. **Discover the service inventory.** Call `list_indexed_services` to get "
            "the full list. If nothing is indexed, stop and tell the user.\n"
            "\n"
            "2. **Profile each service.** For every service, invoke the `service_overview` "
            "prompt — it will identify entry points, domain types, and framework "
            "conventions for that service. Collect those summaries before proceeding.\n"
            "\n"
            "3. **Map inter-service communication.** Search across all services for "
            "outbound call patterns using queries like: "
            '`"http client"`, `"feign client"`, `"rest template"`, '
            '`"grpc stub"`, `"kafka producer"`, `"message publisher"`, '
            '`"event emitter"`, `"amqp"`. '
            "Build a dependency list noting which services are callers and which are "
            "called, and whether communication is synchronous or asynchronous.\n"
            "\n"
            "4. **Identify shared infrastructure.** Search for terms like "
            '`"datasource"`, `"redis"`, `"kafka"`, `"rabbitmq"`, `"s3"`, '
            '`"mongo"`, `"postgres"`, `"elasticsearch"` to surface data stores, '
            "caches, and message brokers. Note which services own vs. share each resource.\n"
            "\n"
            '5. **Find cross-cutting concerns.** Search for `"authentication"`, `"jwt"`, '
            '`"oauth"`, `"tracing"`, `"opentelemetry"`, `"metrics"`, '
            '`"circuit breaker"`, `"retry"`, `"rate limit"` to understand '
            "system-wide conventions.\n"
            "\n"
            "Then write the overview with these sections:\n"
            "\n"
            "- **System Purpose** — 2-3 sentences on what problem this collection of "
            "services solves as a whole.\n"
            "- **Service Inventory** — a table: Service | Purpose | Tech Stack | Entry Style.\n"
            "- **Communication Topology** — synchronous (REST/gRPC) vs asynchronous "
            "(events/queues) interactions. Include a dependency list: "
            "`ServiceA → ServiceB (REST)`, `ServiceC → broker → ServiceD (async)`, etc.\n"
            "- **Data Architecture** — data stores, caches, and message brokers with "
            "ownership notes (owned by one service vs. shared).\n"
            "- **Cross-cutting Concerns** — how authentication, observability (tracing, "
            "metrics, logging), and resilience (retries, circuit breakers) are handled "
            "across the system.\n"
            "- **Key Architectural Patterns** — flag patterns you have evidence for: "
            "event-driven, CQRS, saga, API gateway, BFF, strangler fig, etc.\n"
            "\n"
            "Skip any section you have no evidence for. Do not invent details."
        )
