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
# Conservative character cap (~8 k tokens at ~4 chars/token) to avoid
# "Failed to encode text" 400s on models with limited context windows.
_MAX_TEXT_CHARS = 32_000

# Native output dimensions for known models. The jina-code-embeddings family
# supports Matryoshka truncation via the `dimensions` API parameter —
# override with JINA_API_DIMENSIONS to one of the supported sizes:
#   - jina-code-embeddings-0.5b: 64, 128, 256, 512, 896 (native)
#     https://jina.ai/models/jina-code-embeddings-0.5b
#   - jina-code-embeddings-1.5b: 128, 256, 512, 1024, 1536 (native)
#     https://jina.ai/models/jina-code-embeddings-1.5b
# jina-embeddings-v2-base-code is fixed-size and does not support truncation.
#     https://jina.ai/models/jina-embeddings-v2-base-code
_NATIVE_DIMENSIONS: dict[str, int] = {
    "jina-embeddings-v2-base-code": 768,
    "jina-code-embeddings-0.5b": 896,
    "jina-code-embeddings-1.5b": 1536,
}

# Models that accept the `task` parameter (asymmetric retrieval). The v2 model
# is single-mode and rejects `task`, so we omit it.
_TASK_AWARE_PREFIXES = ("jina-code-embeddings-",)

# jina-code-embeddings models use a different task vocabulary than the generic
# "retrieval.*" tasks accepted by other Jina models.
_JINA_CODE_TASK_MAP = {
    "retrieval.passage": "nl2code.passage",
    "retrieval.query": "nl2code.query",
}


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
        self._uses_code_tasks = self._model.startswith("jina-code-embeddings-")
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

    def _sanitize(self, text: str) -> str:
        # Encode to UTF-8 replacing lone surrogates and other unencodable
        # code points, then decode back — this removes anything that would
        # cause Jina's tokenizer to return 400 "Failed to encode text".
        cleaned = text.encode("utf-8", errors="replace").decode("utf-8")
        cleaned = "".join(ch for ch in cleaned if ch >= " " or ch in "\t\n\r")
        return cleaned[:_MAX_TEXT_CHARS].strip() or "."

    def _make_body(self, inputs: list[str], task: str) -> dict:
        body: dict = {"model": self._model, "input": inputs}
        if self._supports_task:
            body["task"] = (
                _JINA_CODE_TASK_MAP.get(task, task) if self._uses_code_tasks else task
            )
        if self._dims_override is not None:
            body["dimensions"] = self._dims_override
        return body

    async def _post_with_retry(self, body: dict) -> dict:
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
        if resp.status_code >= 400:
            logger.error("Jina API error %d: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp.json()

    async def _embed_batch_with_fallback(
        self, batch: list[str], task: str
    ) -> list[list[float]]:
        """Embed one item at a time, halving on failure, substituting '.' only as last resort."""
        vectors: list[list[float]] = []
        for idx, text in enumerate(batch):
            candidate = text
            embedded = False
            while candidate:
                try:
                    data = await self._post_with_retry(
                        self._make_body([candidate], task)
                    )
                    vectors.append(data["data"][0]["embedding"])
                    if len(candidate) < len(text):
                        logger.info(
                            "Encoded truncated text at batch index %d (%d → %d chars)",
                            idx,
                            len(text),
                            len(candidate),
                        )
                    embedded = True
                    break
                except Exception:
                    half = len(candidate) // 2
                    if half < 64:
                        break
                    logger.warning(
                        "Text at batch index %d (len=%d) failed — retrying with first %d chars",
                        idx,
                        len(candidate),
                        half,
                    )
                    candidate = candidate[:half]
            if not embedded:
                logger.warning(
                    "Skipping unencodable text at batch index %d (original len=%d), using placeholder.",
                    idx,
                    len(text),
                )
                data = await self._post_with_retry(self._make_body(["."], task))
                vectors.append(data["data"][0]["embedding"])
        return vectors

    async def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        if not texts:
            return []
        sanitized = [self._sanitize(t) for t in texts]
        all_vectors: list[list[float]] = []
        for i in range(0, len(sanitized), _BATCH_SIZE):
            batch = sanitized[i : i + _BATCH_SIZE]
            try:
                data = await self._post_with_retry(self._make_body(batch, task))
            except Exception as exc:
                if "400" in str(exc):
                    logger.warning(
                        "Batch of %d failed with 400 — retrying one-by-one", len(batch)
                    )
                    all_vectors.extend(
                        await self._embed_batch_with_fallback(batch, task)
                    )
                    continue
                raise
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
