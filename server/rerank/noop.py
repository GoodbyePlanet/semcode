from __future__ import annotations

from qdrant_client.models import ScoredPoint


class NoopReranker:
    """Passthrough reranker used when RERANKER_ENABLED=false."""

    @property
    def candidate_multiplier(self) -> int:
        return 1

    async def rerank(
        self, query: str, candidates: list[ScoredPoint], top_n: int
    ) -> list[ScoredPoint]:
        return candidates[:top_n]
