from __future__ import annotations

import asyncio
import logging

import httpx

from server.config import settings
from server.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_API_URL = "https://api.voyageai.com/v1/embeddings"
# Voyage caps batch size at 128 inputs per request.
_BATCH_SIZE = 128
_BACKOFF_DELAYS = [10, 20, 30, 40]

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

    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        if not texts:
            return []
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            body: dict = {
                "model": self._model,
                "input": batch,
                "input_type": input_type,
            }
            if self._dims_override is not None:
                body["output_dimension"] = self._dims_override
            for attempt in range(4):
                resp = await self._client.post(_API_URL, json=body)
                if resp.status_code != 429:
                    break
                retry_after = float(resp.headers.get("Retry-After", 0))
                wait = retry_after if retry_after > 0 else _BACKOFF_DELAYS[attempt]
                logger.warning(
                    "Voyage rate-limited (429) — retrying in %.0fs (attempt %d/4)",
                    wait,
                    attempt + 1,
                )
                await asyncio.sleep(wait)
            resp.raise_for_status()
            data = resp.json()
            batch_vectors = [item["embedding"] for item in data.get("data", [])]
            if len(batch_vectors) != len(batch):
                raise ValueError(
                    f"Voyage returned {len(batch_vectors)} vectors for "
                    f"{len(batch)} inputs — response may be malformed"
                )
            all_vectors.extend(batch_vectors)
        return all_vectors

    async def close(self) -> None:
        await self._client.aclose()
