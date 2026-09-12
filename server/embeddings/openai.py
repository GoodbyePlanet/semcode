from __future__ import annotations

import httpx

from server.config import settings
from server.embeddings.base import EmbeddingProvider
from server.embeddings.http_batch import embed_in_batches

_API_URL = "https://api.openai.com/v1/embeddings"
# OpenAI accepts up to 2048 inputs per request; 128 is conservative and matches
# Voyage's cap, so behavior is uniform across providers.
_BATCH_SIZE = 128

_NATIVE_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-large": 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embeddings — see https://platform.openai.com/docs/api-reference/embeddings."""

    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set but EMBEDDINGS_PROVIDER=openai."
            )
        self._api_key = settings.openai_api_key
        self._model = settings.openai_embedding_model
        self._dims_override = settings.openai_dimensions
        if self._dims_override is not None:
            self._dims = self._dims_override
        elif self._model in _NATIVE_DIMENSIONS:
            self._dims = _NATIVE_DIMENSIONS[self._model]
        else:
            raise RuntimeError(
                f"Unknown OpenAI embedding model {self._model!r} — set "
                "OPENAI_DIMENSIONS to declare the output size, or use a known model "
                f"({', '.join(sorted(_NATIVE_DIMENSIONS))})."
            )
        self._client = httpx.AsyncClient(
            timeout=120.0,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    @property
    def dimensions(self) -> int:
        return self._dims

    def _make_body(self, inputs: list[str]) -> dict:
        body: dict = {"model": self._model, "input": inputs}
        if self._dims_override is not None:
            body["dimensions"] = self._dims_override
        return body

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await embed_in_batches(
            texts,
            client=self._client,
            url=_API_URL,
            provider="OpenAI",
            batch_size=_BATCH_SIZE,
            make_body=self._make_body,
            extract=lambda data: [item["embedding"] for item in data.get("data", [])],
        )

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0] if vectors else []

    async def close(self) -> None:
        await self._client.aclose()


from server.embeddings.factory import register

register("openai", OpenAIEmbeddingProvider)
