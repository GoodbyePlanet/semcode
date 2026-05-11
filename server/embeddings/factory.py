from __future__ import annotations

from server.config import settings
from server.embeddings.base import EmbeddingProvider

_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    global _provider
    if _provider is not None:
        return _provider

    name = settings.embeddings_provider
    if name == "jina":
        from server.embeddings.jina import JinaEmbeddingProvider

        _provider = JinaEmbeddingProvider()
    elif name == "voyage":
        from server.embeddings.voyage import VoyageEmbeddingProvider

        _provider = VoyageEmbeddingProvider()
    elif name == "openai":
        from server.embeddings.openai import OpenAIEmbeddingProvider

        _provider = OpenAIEmbeddingProvider()
    elif name == "ollama":
        from server.embeddings.ollama import OllamaEmbeddingProvider

        _provider = OllamaEmbeddingProvider()
    else:
        raise ValueError(
            f"Unknown EMBEDDINGS_PROVIDER {name!r}. "
            "Expected one of: jina, voyage, openai, ollama."
        )
    return _provider


async def close_embedding_provider() -> None:
    global _provider
    if _provider is None:
        return
    close = getattr(_provider, "close", None)
    if close is not None:
        await close()
    _provider = None
