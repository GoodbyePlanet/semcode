from __future__ import annotations

import re

# Suffix joins are only emitted for the first N subwords of an identifier. The
# joins are O(k^2) in total characters for k subwords, and their value drops off
# fast — nobody starts a lookup nine subwords into a name.
MAX_SUFFIX_JOIN_SUBWORDS = 8


def split_code_identifiers(text: str) -> str:
    """Split camelCase/PascalCase/snake_case into subwords; keep originals alongside.

    Both the original tokens and their subword splits are returned so BM25
    matches exact identifiers (PlaceOrderRequest) AND partial queries (place order).
    """
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", expanded)
    expanded = expanded.replace("_", " ")
    expanded = expanded.replace("-", " ")
    return text + "\n" + expanded


def symbol_name_tokens(name: str) -> str:
    """Build the text indexed behind `find_symbol(exact=False)`.

    Extends `split_code_identifiers()` with *suffix joins* — the identifier
    re-joined from each subword boundary onwards. Without them, a `PREFIX`
    full-text index only matches a query that prefixes the whole identifier or
    one single subword, so `WebAuth` would miss `GetWebAuthnSession`: the query
    spans `Web` + `Authn` but is not anchored at the start of the name. Emitting
    `WebAuthnSession` as its own token makes that a real index hit.

    Suffix joins are skipped for names containing whitespace (markdown headings,
    CSS selector lists, dependency coordinates). Those are prose rather than
    concatenated identifiers — their words are already separate tokens, so joins
    would add nothing but index bulk.
    """
    base = split_code_identifiers(name)
    if re.search(r"\s", name):
        return base

    subwords = base.split("\n", 1)[1].split()
    if len(subwords) < 2:
        return base

    capped = subwords[:MAX_SUFFIX_JOIN_SUBWORDS]
    joins = ["".join(capped[i:]) for i in range(1, len(capped))]
    # dict.fromkeys dedupes while preserving order; a join can repeat the
    # original name (snake_case) or a lone trailing subword.
    extra = [j for j in dict.fromkeys(joins) if j not in {name, *subwords}]
    return base + ("\n" + " ".join(extra) if extra else "")
