from __future__ import annotations

import httpx

from server.config import settings
from server.embeddings.base import EmbeddingProvider
from server.embeddings.http_batch import embed_in_batches

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

    @staticmethod
    def _extract(data) -> list[list[float]]:
        # TEI returns a list of vectors directly
        if isinstance(data, list):
            return data
        # fallback: OpenAI-style { "data": [...] }
        return [item["embedding"] for item in data.get("data", [])]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await embed_in_batches(
            texts,
            client=self._client,
            url=f"{self._base_url}{_EMBED_PATH}",
            provider="Embedding server",
            batch_size=_BATCH_SIZE,
            make_body=lambda batch: {"inputs": batch},
            extract=self._extract,
        )

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0] if vectors else []

    async def close(self) -> None:
        await self._client.aclose()


from server.embeddings.factory import register

register("jina", JinaEmbeddingProvider)
