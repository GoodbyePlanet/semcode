from __future__ import annotations

from server.embeddings.code_tokenizer import split_code_identifiers


def _tokens(text: str) -> set[str]:
    return set(split_code_identifiers(text).lower().split())


def test_pascal_case_splits_to_subwords():
    tokens = _tokens("PlaceOrderRequest")
    assert "place" in tokens
    assert "order" in tokens
    assert "request" in tokens


def test_pascal_case_keeps_original():
    result = split_code_identifiers("PlaceOrderRequest")
    assert "PlaceOrderRequest" in result


def test_camel_case_splits_and_keeps_original():
    tokens = _tokens("useAuth")
    assert "use" in tokens
    assert "auth" in tokens
    result = split_code_identifiers("useAuth")
    assert "useAuth" in result


def test_acronym_handler_splits():
    tokens = _tokens("HTTPSConnection")
    assert "https" in tokens
    assert "connection" in tokens
    result = split_code_identifiers("HTTPSConnection")
    assert "HTTPSConnection" in result


def test_snake_case_splits_and_keeps_original():
    result = split_code_identifiers("place_order")
    tokens = set(result.lower().split())
    assert "place" in tokens
    assert "order" in tokens
    assert "place_order" in result


def test_idempotent_token_set():
    text = "PlaceOrderRequest"
    once = set(split_code_identifiers(text).lower().split())
    twice = set(split_code_identifiers(split_code_identifiers(text)).lower().split())
    assert once == twice
