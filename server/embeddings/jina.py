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
        self._base_url = settings.jina_url.rstrip("/")
        self._dims = settings.jina_dimensions
        self._client = httpx.AsyncClient(timeout=120.0)

    @property
    def dimensions(self) -> int:
        return self._dims

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            resp = await self._client.post(
                f"{self._base_url}{_EMBED_PATH}",
                json={"inputs": batch},
            )
            resp.raise_for_status()
            data = resp.json()
            # TEI returns a list of vectors directly
            if isinstance(data, list):
                batch_vectors: list[list[float]] = data
            else:
                # fallback: OpenAI-style { "data": [...] }
                batch_vectors = [item["embedding"] for item in data.get("data", [])]
            if len(batch_vectors) != len(batch):
                raise ValueError(
                    f"Embedding server returned {len(batch_vectors)} vectors for "
                    f"{len(batch)} inputs — response may be malformed"
                )
            all_vectors.extend(batch_vectors)
        return all_vectors

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0] if vectors else []

    async def close(self) -> None:
        await self._client.aclose()


from server.embeddings.factory import register  # noqa: E402

register("jina", JinaEmbeddingProvider)
