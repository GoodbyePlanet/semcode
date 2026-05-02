from __future__ import annotations


def recall_at_k(ranks: list[int | None], k: int) -> float:
    """Fraction of cases where the first correct hit appeared at rank <= k."""
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def mrr(ranks: list[int | None]) -> float:
    """Mean Reciprocal Rank — 1/rank of first correct hit, averaged across cases."""
    if not ranks:
        return 0.0
    return sum(1 / r for r in ranks if r is not None) / len(ranks)
