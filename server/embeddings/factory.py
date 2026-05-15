from __future__ import annotations

from server.config import settings
from server.embeddings.base import EmbeddingProvider

_registry: dict[str, type[EmbeddingProvider]] = {}
_provider: EmbeddingProvider | None = None


def register(name: str, cls: type[EmbeddingProvider]) -> None:
    _registry[name] = cls


def get_embedding_provider() -> EmbeddingProvider:
    global _provider
    if _provider is not None:
        return _provider

    name = settings.embeddings_provider
    cls = _registry.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown EMBEDDINGS_PROVIDER {name!r}. "
            f"Expected one of: {', '.join(sorted(_registry))}."
        )
    _provider = cls()
    return _provider


async def close_embedding_provider() -> None:
    global _provider
    if _provider is None:
        return
    close = getattr(_provider, "close", None)
    if close is not None:
        await close()
    _provider = None
