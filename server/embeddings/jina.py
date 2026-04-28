from __future__ import annotations

import logging

import httpx

from server.config import settings
from server.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)

# HuggingFace TEI uses the OpenAI-compatible /embed endpoint
_EMBED_PATH = "/embed"
_BATCH_SIZE = 32


class JinaEmbeddingProvider(EmbeddingProvider):
    """Calls the self-hosted Jina Code V2 model via HuggingFace Text Embeddings Inference."""

    def __init__(self) -> None:
        self._base_url = settings.embeddings_url.rstrip("/")
        self._dims = settings.embeddings_dimensions

    @property
    def dimensions(self) -> int:
        return self._dims

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        all_vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=120.0) as client:
            for i in range(0, len(texts), _BATCH_SIZE):
                batch = texts[i : i + _BATCH_SIZE]
                resp = await client.post(
                    f"{self._base_url}{_EMBED_PATH}",
                    json={"inputs": batch},
                )
                resp.raise_for_status()
                data = resp.json()
                # TEI returns a list of vectors directly
                if isinstance(data, list):
                    all_vectors.extend(data)
                else:
                    # fallback: OpenAI-style { "data": [...] }
                    for item in data.get("data", []):
                        all_vectors.append(item["embedding"])
        return all_vectors

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0] if vectors else []


_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        _provider = JinaEmbeddingProvider()
    return _provider
