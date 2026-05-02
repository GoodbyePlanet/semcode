from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate search_code retrieval quality against a golden dataset."
    )
    parser.add_argument("--dataset", required=True, help="Path to a YAML query dataset file")
    parser.add_argument(
        "--mode",
        default="baseline",
        choices=["baseline", "rerank"],
        help="baseline = vector search only; rerank = vector + cross-encoder",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write JSON results (auto-generated if omitted)",
    )
    parser.add_argument(
        "--top-k",
        nargs="+",
        type=int,
        default=[1, 3, 5, 10],
        metavar="K",
        help="K values for Recall@K (default: 1 3 5 10)",
    )
    args = parser.parse_args()

    output = args.output
    if output is None:
        ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        stem = Path(args.dataset).stem
        output = f"eval/results/{stem}-{args.mode}-{ts}.json"

    from eval.runner import run_evaluation

    asyncio.run(
        run_evaluation(
            dataset_path=args.dataset,
            mode=args.mode,
            top_k_values=args.top_k,
            output_path=output,
        )
    )


if __name__ == "__main__":
    main()
