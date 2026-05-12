from __future__ import annotations

import asyncio
import logging

import httpx

from server.config import settings
from server.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_API_URL = "https://api.jina.ai/v1/embeddings"
# Jina's hosted API accepts up to 2048 inputs per request; 128 keeps us
# uniform with the OpenAI/Voyage providers.
_BATCH_SIZE = 128
_BACKOFF_DELAYS = [10, 20, 30, 40]

# Native output dimensions for known models. v3 and the jina-code-embeddings
# family support Matryoshka truncation via the `dimensions` API parameter —
# override with JINA_API_DIMENSIONS.
#
# Other code-tuned models available on the hosted API:
#   - jina-code-embeddings-0.5b
#   - jina-code-embeddings-1.5b
# Their native dimensions vary; set JINA_API_DIMENSIONS to declare the size.
_NATIVE_DIMENSIONS: dict[str, int] = {
    "jina-embeddings-v2-base-code": 768,
    "jina-embeddings-v2-base-en": 768,
    "jina-embeddings-v3": 1024,
    "jina-clip-v2": 1024,
}

# Models that accept the `task` parameter (asymmetric retrieval). v2 models
# are single-mode and reject `task`, so we omit it for them.
_TASK_AWARE_PREFIXES = ("jina-embeddings-v3", "jina-code-embeddings-")


class JinaApiEmbeddingProvider(EmbeddingProvider):
    """Jina AI hosted embeddings — see https://jina.ai/embeddings/."""

    def __init__(self) -> None:
        if not settings.jina_api_key:
            raise RuntimeError(
                "JINA_API_KEY is not set but EMBEDDINGS_PROVIDER=jina-api."
            )
        self._api_key = settings.jina_api_key
        self._model = settings.jina_api_model
        self._dims_override = settings.jina_api_dimensions
        if self._dims_override is not None:
            self._dims = self._dims_override
        elif self._model in _NATIVE_DIMENSIONS:
            self._dims = _NATIVE_DIMENSIONS[self._model]
        else:
            raise RuntimeError(
                f"Unknown Jina model {self._model!r} — set JINA_API_DIMENSIONS "
                "to declare the output size, or use a known model "
                f"({', '.join(sorted(_NATIVE_DIMENSIONS))})."
            )
        self._supports_task = self._model.startswith(_TASK_AWARE_PREFIXES)
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
        return await self._embed(texts, task="retrieval.passage")

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([text], task="retrieval.query")
        return vectors[0] if vectors else []

    async def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        if not texts:
            return []
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            body: dict = {"model": self._model, "input": batch}
            if self._supports_task:
                body["task"] = task
            if self._dims_override is not None:
                body["dimensions"] = self._dims_override
            for attempt in range(4):
                resp = await self._client.post(_API_URL, json=body)
                if resp.status_code != 429:
                    break
                retry_after = float(resp.headers.get("Retry-After", 0))
                wait = retry_after if retry_after > 0 else _BACKOFF_DELAYS[attempt]
                logger.warning(
                    "Jina rate-limited (429) — retrying in %.0fs (attempt %d/4)",
                    wait,
                    attempt + 1,
                )
                await asyncio.sleep(wait)
            resp.raise_for_status()
            data = resp.json()
            batch_vectors = [item["embedding"] for item in data.get("data", [])]
            if len(batch_vectors) != len(batch):
                raise ValueError(
                    f"Jina returned {len(batch_vectors)} vectors for "
                    f"{len(batch)} inputs — response may be malformed"
                )
            all_vectors.extend(batch_vectors)
        return all_vectors

    async def close(self) -> None:
        await self._client.aclose()
