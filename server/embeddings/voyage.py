from __future__ import annotations

import httpx

from server.config import settings
from server.embeddings.base import EmbeddingProvider
from server.embeddings.http_batch import embed_in_batches

_API_URL = "https://api.voyageai.com/v1/embeddings"
# Voyage caps batch size at 128 inputs per request.
_BATCH_SIZE = 128

# Native output dimensions for known models. Some models (voyage-code-3, voyage-3,
# voyage-3-large) accept an `output_dimension` API parameter to shrink/grow this;
# users override via VOYAGE_DIMENSIONS.
_NATIVE_DIMENSIONS: dict[str, int] = {
    "voyage-code-3": 1024,
    "voyage-3": 1024,
    "voyage-3-large": 1024,
    "voyage-3-lite": 512,
    "voyage-large-2": 1536,
    "voyage-2": 1024,
    "voyage-code-2": 1536,
}


class VoyageEmbeddingProvider(EmbeddingProvider):
    """Voyage AI embeddings — see https://docs.voyageai.com/reference/embeddings-api."""

    def __init__(self) -> None:
        if not settings.voyage_api_key:
            raise RuntimeError(
                "VOYAGE_API_KEY is not set but EMBEDDINGS_PROVIDER=voyage."
            )
        self._api_key = settings.voyage_api_key
        self._model = settings.voyage_model
        self._dims_override = settings.voyage_dimensions
        if self._dims_override is not None:
            self._dims = self._dims_override
        elif self._model in _NATIVE_DIMENSIONS:
            self._dims = _NATIVE_DIMENSIONS[self._model]
        else:
            raise RuntimeError(
                f"Unknown Voyage model {self._model!r} — set VOYAGE_DIMENSIONS "
                "to declare the output size, or use a known model "
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

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, input_type="document")

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([text], input_type="query")
        return vectors[0] if vectors else []

    def _make_body(self, inputs: list[str], input_type: str) -> dict:
        body: dict = {
            "model": self._model,
            "input": inputs,
            "input_type": input_type,
        }
        if self._dims_override is not None:
            body["output_dimension"] = self._dims_override
        return body

    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        return await embed_in_batches(
            texts,
            client=self._client,
            url=_API_URL,
            provider="Voyage",
            batch_size=_BATCH_SIZE,
            make_body=lambda batch: self._make_body(batch, input_type),
            extract=lambda data: [item["embedding"] for item in data.get("data", [])],
        )

    async def close(self) -> None:
        await self._client.aclose()


from server.embeddings.factory import register

register("voyage", VoyageEmbeddingProvider)
