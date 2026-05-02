from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from server.config import settings
from server.embeddings.jina import JinaEmbeddingProvider
from server.store.qdrant import QdrantStore
from eval.matching import find_first_correct_rank
from eval.metrics import mrr, recall_at_k

logger = logging.getLogger(__name__)

_TOP_K_VALUES = [1, 3, 5, 10]
# Fetch enough candidates so that each k value can be evaluated
_MAX_CANDIDATES = 50


async def run_evaluation(
    dataset_path: str,
    mode: str = "baseline",
    top_k_values: list[int] | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    if top_k_values is None:
        top_k_values = _TOP_K_VALUES

    cases = _load_dataset(dataset_path)
    if not cases:
        raise ValueError(f"No cases found in {dataset_path}")

    embedder = JinaEmbeddingProvider()
    store = QdrantStore()
    reranker = _build_reranker(mode)
    candidate_limit = max(top_k_values) * reranker.candidate_multiplier

    results_per_case = []
    for case in cases:
        query = case["query"]
        filters = case.get("filters") or {}
        expected = case.get("expected") or []

        query_vector = await embedder.embed_query(query)
        hits = await store.search(
            query_vector=query_vector,
            limit=candidate_limit,
            language=filters.get("language"),
            service=filters.get("service"),
            symbol_type=filters.get("symbol_type"),
        )
        hits = await reranker.rerank(query, hits, top_n=max(top_k_values))

        rank = find_first_correct_rank(hits, expected)
        results_per_case.append({
            "id": case.get("id", "?"),
            "query": query,
            "language": filters.get("language"),
            "first_correct_rank": rank,
            "hit": rank is not None,
        })

    ranks = [r["first_correct_rank"] for r in results_per_case]
    aggregate = {
        **{f"recall@{k}": recall_at_k(ranks, k) for k in top_k_values},
        "mrr": mrr(ranks),
        "total_cases": len(ranks),
        "hits": sum(1 for r in ranks if r is not None),
    }

    by_language: dict[str, list[int | None]] = defaultdict(list)
    for r in results_per_case:
        if lang := r.get("language"):
            by_language[lang].append(r["first_correct_rank"])
    per_language = {
        lang: {
            **{f"recall@{k}": recall_at_k(lang_ranks, k) for k in top_k_values},
            "mrr": mrr(lang_ranks),
            "total_cases": len(lang_ranks),
        }
        for lang, lang_ranks in by_language.items()
    }

    output = {
        "dataset": dataset_path,
        "mode": mode,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "aggregate": aggregate,
        "per_language": per_language,
        "cases": results_per_case,
    }

    _print_table(aggregate, per_language, top_k_values)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(output, indent=2))
        print(f"\nResults written to {output_path}")

    return output


def _load_dataset(path: str) -> list[dict]:
    with open(path) as f:
        return yaml.safe_load(f) or []


def _print_table(aggregate: dict, per_language: dict, top_k_values: list[int]) -> None:
    print(f"\n{'='*60}")
    print(f"  OVERALL  ({aggregate['hits']}/{aggregate['total_cases']} cases with a hit)")
    print(f"{'='*60}")
    for k in top_k_values:
        val = aggregate.get(f"recall@{k}", 0)
        bar = "█" * int(val * 20)
        print(f"  Recall@{k:<2}  {val:.3f}  {bar}")
    print(f"  MRR       {aggregate['mrr']:.3f}")

    if per_language:
        print(f"\n{'─'*60}")
        for lang, stats in sorted(per_language.items()):
            print(f"  {lang} ({stats['total_cases']} cases)")
            for k in top_k_values:
                val = stats.get(f"recall@{k}", 0)
                print(f"    Recall@{k}: {val:.3f}")
            print(f"    MRR: {stats['mrr']:.3f}")


def _build_reranker(mode: str):
    if mode == "rerank":
        from server.rerank.tei_reranker import TeiReranker
        return TeiReranker()
    from server.rerank.noop import NoopReranker
    return NoopReranker()
