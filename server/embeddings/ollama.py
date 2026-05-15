from __future__ import annotations

import logging

import httpx

from server.config import settings
from server.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_EMBED_PATH = "/api/embed"
_BATCH_SIZE = 32

_NATIVE_DIMENSIONS: dict[str, int] = {
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
    "snowflake-arctic-embed": 1024,
    "bge-m3": 1024,
}


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama embeddings — see https://github.com/ollama/ollama/blob/main/docs/api.md#generate-embeddings."""

    def __init__(self) -> None:
        self._base_url = settings.ollama_url.rstrip("/")
        self._model = settings.ollama_model
        self._dims_override = settings.ollama_dimensions
        if self._dims_override is not None:
            self._dims = self._dims_override
        elif self._model in _NATIVE_DIMENSIONS:
            self._dims = _NATIVE_DIMENSIONS[self._model]
        else:
            raise RuntimeError(
                f"Unknown Ollama model {self._model!r} — set OLLAMA_DIMENSIONS "
                "to declare the output size, or use a known model "
                f"({', '.join(sorted(_NATIVE_DIMENSIONS))})."
            )
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
                json={"model": self._model, "input": batch},
            )
            resp.raise_for_status()
            data = resp.json()
            batch_vectors = data.get("embeddings", [])
            if len(batch_vectors) != len(batch):
                raise ValueError(
                    f"Ollama returned {len(batch_vectors)} vectors for "
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

register("ollama", OllamaEmbeddingProvider)
