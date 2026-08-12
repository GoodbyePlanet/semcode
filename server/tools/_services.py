from __future__ import annotations

from server.state import get_service_registry
from server.store.service_registry import load_effective_services


async def unknown_service_message(service: str) -> str:
    """Explain an unknown-service lookup in terms of what the server can actually see.

    The effective service list merges config.yaml with dynamically-registered
    services, so a miss has two very different causes: a genuine typo, or a server
    that loaded no config at all (e.g. config.yaml not mounted into the container).
    Listing the known names tells those apart instead of guessing at config.yaml.
    """
    services = await load_effective_services(get_service_registry())
    if not services:
        return (
            f"Service `{service}` not found — this server has no services at all "
            f"(config.yaml is empty or was never loaded, and nothing is registered)."
        )
    known = ", ".join(f"`{s.name}`" for s in sorted(services, key=lambda s: s.name))
    return f"Service `{service}` not found. Known services: {known}."
