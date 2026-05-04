#!/usr/bin/env python3
"""
Seed TEST_CASES for validate_hybrid.py from real Qdrant data.

Scrolls the code_symbols collection, picks multi-word identifiers across
all meaningful symbol types, and prints a ready-to-paste TEST_CASES list
with up to five query styles per symbol:

  1. exact      -- the identifier as written        (e.g. "PlaceOrderRequest")
  2. tokenized  -- split into lowercase words       (e.g. "place order request")
  3. snake_case -- tokenized words joined with _    (e.g. "place_order_request")
  4. prefix     -- first two tokenized words only   (e.g. "place order")
  5. semantic   -- first sentence of docstring      (skipped when no docstring)

Review semantic entries before pasting: remove any whose docstring sentence
does not clearly describe the symbol on its own.

Usage:
    uv run scripts/seed_test_cases.py
    uv run scripts/seed_test_cases.py --per-bucket 5 --scan-limit 1000
    uv run scripts/seed_test_cases.py --url http://localhost:6333 --collection code_symbols
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

# All symbol types that produce multi-word identifiers worth testing.
# Ordered so the most common ones come first in the output.
SYMBOL_TYPES = [
    "class",
    "method",
    "function",
    "interface",
    "constructor",
    "enum",
    "record",
    "pydantic_model",
    "dataclass",
    "react_component",
    "react_hook",
]

DEFAULT_PER_BUCKET = 5
DEFAULT_SCAN_LIMIT = 500


@dataclass
class Candidate:
    symbol_name: str
    symbol_type: str
    docstring: str | None


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def is_multi_word(name: str) -> bool:
    """True when the identifier has at least two word components."""
    has_camel = bool(re.search(r"[a-z][A-Z]", name))
    has_pascal = bool(re.search(r"^[A-Z][a-z]+[A-Z]", name))
    has_snake = "_" in name and len(name.split("_")) >= 2
    return has_camel or has_pascal or has_snake


def tokenize(name: str) -> str:
    """Split camelCase / PascalCase / snake_case into lowercase words."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    s = s.replace("_", " ").replace("-", " ")
    return s.lower().strip()


def to_snake_case(name: str) -> str:
    """Convert any identifier to snake_case."""
    return tokenize(name).replace(" ", "_")


def prefix_query(name: str, words: int = 2) -> str | None:
    """First `words` words of the tokenized name, or None if too few words."""
    parts = tokenize(name).split()
    if len(parts) <= words:
        return None
    return " ".join(parts[:words])


def first_sentence(docstring: str) -> str | None:
    """Return the first useful sentence from a docstring, or None."""
    cleaned = re.sub(r"^(\"\"\"|'''|/\*\*?|//)\s*", "", docstring.strip())
    cleaned = re.sub(r'\s*(\"\"\"|\'\'\'|\*/)$', "", cleaned)
    # Collapse javadoc/jsdoc continuation lines ("  * text" → " text")
    cleaned = re.sub(r"\n\s*\*\s?", " ", cleaned).strip()
    # Drop @param / @return / @throws tags — not useful as queries
    cleaned = re.sub(r"@\w+[^\n]*", "", cleaned).strip()
    sentence = re.split(r"(?<=[.!?])\s", cleaned)[0].strip().rstrip(".")
    if len(sentence) < 15:
        return None
    return sentence


# ---------------------------------------------------------------------------
# Test-case generation
# ---------------------------------------------------------------------------

def make_test_cases(c: Candidate) -> list[tuple[str, str, str]]:
    """Return (query, expected_symbol_name, kind) triples for one candidate."""
    cases: list[tuple[str, str, str]] = []
    tokens = tokenize(c.symbol_name)

    # 1. exact
    cases.append((c.symbol_name, c.symbol_name, "exact"))

    # 2. tokenized — only if it differs from the raw name
    if tokens != c.symbol_name.lower():
        cases.append((tokens, c.symbol_name, "tokenized"))

    # 3. snake_case — only if it differs from both the raw name and tokenized
    snake = to_snake_case(c.symbol_name)
    if snake != c.symbol_name and snake != c.symbol_name.lower():
        cases.append((snake, c.symbol_name, "snake_case"))

    # 4. prefix — only when the name has more than two words
    prefix = prefix_query(c.symbol_name)
    if prefix:
        cases.append((prefix, c.symbol_name, "prefix"))

    # 5. semantic — first sentence of docstring when present
    if c.docstring:
        sentence = first_sentence(c.docstring)
        if sentence:
            cases.append((sentence, c.symbol_name, "semantic"))

    return cases


# ---------------------------------------------------------------------------
# Qdrant sampling
# ---------------------------------------------------------------------------

async def scroll_bucket(
    client: AsyncQdrantClient,
    collection: str,
    symbol_type: str,
    scan_limit: int,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    offset = None
    fetched = 0

    while fetched < scan_limit:
        batch_size = min(200, scan_limit - fetched)
        results, offset = await client.scroll(
            collection_name=collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="symbol_type", match=MatchValue(value=symbol_type))]
            ),
            limit=batch_size,
            offset=offset,
            with_payload=["symbol_name", "symbol_type", "docstring"],
            with_vectors=False,
        )
        for point in results:
            name = (point.payload.get("symbol_name") or "").strip()
            if name and is_multi_word(name):
                candidates.append(
                    Candidate(
                        symbol_name=name,
                        symbol_type=symbol_type,
                        docstring=point.payload.get("docstring"),
                    )
                )
        fetched += len(results)
        if offset is None:
            break

    return candidates


def pick_diverse(candidates: list[Candidate], n: int) -> list[Candidate]:
    """
    Pick n candidates with name diversity:
    - Deduplicate by exact symbol_name.
    - Group by the first tokenized word; take at most ceil(n/groups) per group
      so we don't end up with e.g. five "get*" methods and nothing else.
    - Within each group prefer longer names (more tokenization surface).
    """
    seen_names: set[str] = set()
    by_first_word: dict[str, list[Candidate]] = {}

    for c in candidates:
        if c.symbol_name in seen_names:
            continue
        seen_names.add(c.symbol_name)
        first_word = tokenize(c.symbol_name).split()[0]
        by_first_word.setdefault(first_word, []).append(c)

    # Sort within each group by name length descending
    for group in by_first_word.values():
        group.sort(key=lambda c: len(c.symbol_name), reverse=True)

    # Round-robin across groups until we have n candidates
    picked: list[Candidate] = []
    groups = list(by_first_word.values())
    i = 0
    while len(picked) < n and groups:
        idx = i % len(groups)
        group = groups[idx]
        if group:
            picked.append(group.pop(0))
            if not group:
                groups.pop(idx)
                i = max(0, i - 1)
            else:
                i += 1
        else:
            groups.pop(idx)

    return picked


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------

def render(all_cases: list[tuple[str, str, str, str]]) -> str:
    """Render a ready-to-paste TEST_CASES block."""
    lines = ["TEST_CASES = ["]
    current_symbol = None

    for query, expected, kind, symbol_type in all_cases:
        if expected != current_symbol:
            if current_symbol is not None:
                lines.append("")
            lines.append(f"    # {symbol_type}: {expected}")
            current_symbol = expected

        padding = " " * max(1, 52 - len(repr(query)))
        lines.append(f"    ({query!r},{padding}{expected!r}),  # {kind}")

    lines.append("]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main(url: str, collection: str, per_bucket: int, scan_limit: int) -> None:
    client = AsyncQdrantClient(url=url)
    try:
        info = await client.get_collection(collection)
        print(f"# Collection '{collection}' — {info.points_count} points total", file=sys.stderr)

        # (query, expected_name, kind, symbol_type)
        all_cases: list[tuple[str, str, str, str]] = []

        for symbol_type in SYMBOL_TYPES:
            candidates = await scroll_bucket(client, collection, symbol_type, scan_limit)
            picked = pick_diverse(candidates, per_bucket)
            print(
                f"# {symbol_type}: scanned up to {scan_limit}, "
                f"found {len(candidates)} multi-word, picked {len(picked)}",
                file=sys.stderr,
            )
            for c in picked:
                for query, expected, kind in make_test_cases(c):
                    all_cases.append((query, expected, kind, symbol_type))

        if not all_cases:
            print(
                "# No multi-word identifiers found — is the collection indexed?",
                file=sys.stderr,
            )
            sys.exit(1)

        print()
        print(render(all_cases))

    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--url",
        default=os.getenv("QDRANT_URL", "http://localhost:6333"),
        help="Qdrant URL (default: $QDRANT_URL or http://localhost:6333)",
    )
    parser.add_argument(
        "--collection",
        default=os.getenv("QDRANT_COLLECTION", "code_symbols"),
        help="Collection name (default: $QDRANT_COLLECTION or code_symbols)",
    )
    parser.add_argument(
        "--per-bucket",
        type=int,
        default=DEFAULT_PER_BUCKET,
        metavar="N",
        help=f"Symbols to pick per symbol type (default: {DEFAULT_PER_BUCKET})",
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=DEFAULT_SCAN_LIMIT,
        metavar="N",
        help=f"Max points to scan per symbol type (default: {DEFAULT_SCAN_LIMIT})",
    )
    args = parser.parse_args()
    asyncio.run(main(args.url, args.collection, args.per_bucket, args.scan_limit))
