from __future__ import annotations

import logging

import httpx
from qdrant_client.models import ScoredPoint

from server.config import settings

logger = logging.getLogger(__name__)

_RERANK_PATH = "/rerank"


class TeiReranker:
    """Cross-encoder reranker backed by a HuggingFace TEI /rerank endpoint."""

    def __init__(self) -> None:
        self._base_url = settings.reranker_url.rstrip("/")

    @property
    def candidate_multiplier(self) -> int:
        return settings.reranker_candidate_multiplier

    async def rerank(
        self, query: str, candidates: list[ScoredPoint], top_n: int
    ) -> list[ScoredPoint]:
        if not candidates:
            return candidates

        texts = [_candidate_text(c.payload) for c in candidates]
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self._base_url}{_RERANK_PATH}",
                    json={"query": query, "texts": texts, "top_n": top_n},
                )
                resp.raise_for_status()
                ranked = resp.json()
        except Exception as exc:
            logger.warning("Reranker unavailable, falling back to vector order: %s", exc)
            return candidates[:top_n]

        return [candidates[item["index"]] for item in ranked[:top_n]]


def _candidate_text(payload: dict) -> str:
    parts: list[str] = []
    if signature := payload.get("signature"):
        parts.append(signature)
    if docstring := payload.get("docstring"):
        parts.append(docstring[:200])
    if source := payload.get("source"):
        parts.append(source[:400])
    return "\n".join(filter(None, parts))
