from __future__ import annotations

import re


def split_code_identifiers(text: str) -> str:
    """Split camelCase/PascalCase/snake_case into subwords; keep originals alongside.

    Both the original tokens and their subword splits are returned so BM25
    matches exact identifiers (PlaceOrderRequest) AND partial queries (place order).
    """
    expanded = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    expanded = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', expanded)
    expanded = expanded.replace('_', ' ')
    expanded = expanded.replace('-', ' ')
    return text + "\n" + expanded
