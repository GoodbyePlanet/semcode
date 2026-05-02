from __future__ import annotations

from typing import Protocol, runtime_checkable

from qdrant_client.models import ScoredPoint


@runtime_checkable
class Reranker(Protocol):
    @property
    def candidate_multiplier(self) -> int:
        """How many extra candidates to fetch from Qdrant before reranking."""
        ...

    async def rerank(
        self, query: str, candidates: list[ScoredPoint], top_n: int
    ) -> list[ScoredPoint]:
        """Return candidates re-ordered by relevance, trimmed to top_n."""
        ...
