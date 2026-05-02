from __future__ import annotations

from qdrant_client.models import ScoredPoint


def find_first_correct_rank(
    hits: list[ScoredPoint],
    expected: list[dict],
) -> int | None:
    """Return 1-based rank of the first hit that satisfies any expected entry, or None."""
    for rank, hit in enumerate(hits, 1):
        if any(_matches(hit.payload, exp) for exp in expected):
            return rank
    return None


def _matches(payload: dict, expected: dict) -> bool:
    if "symbol_name" in expected:
        hit_name = (payload.get("symbol_name") or "").lower()
        if expected["symbol_name"].lower() not in hit_name:
            return False
    if "file_path_contains" in expected:
        hit_path = (payload.get("file_path") or "").lower()
        if expected["file_path_contains"].lower() not in hit_path:
            return False
    return True
