from __future__ import annotations

import pytest

from server.embeddings.code_tokenizer import (
    MAX_SUFFIX_JOIN_SUBWORDS,
    split_code_identifiers,
    symbol_name_tokens,
)


def _tokens(text: str) -> set[str]:
    return set(split_code_identifiers(text).lower().split())


def _indexed(name: str) -> set[str]:
    """Tokens Qdrant's PREFIX tokenizer would see for a symbol name."""
    return set(symbol_name_tokens(name).lower().split())


def _matches(name: str, query: str) -> bool:
    """Whether a PREFIX-tokenized query would be a real index hit for `name`."""
    return any(token.startswith(query.lower()) for token in _indexed(name))


def test_pascal_case_splits_to_subwords() -> None:
    tokens = _tokens("PlaceOrderRequest")
    assert "place" in tokens
    assert "order" in tokens
    assert "request" in tokens


def test_pascal_case_keeps_original() -> None:
    result = split_code_identifiers("PlaceOrderRequest")
    assert "PlaceOrderRequest" in result


def test_camel_case_splits_and_keeps_original() -> None:
    tokens = _tokens("useAuth")
    assert "use" in tokens
    assert "auth" in tokens
    result = split_code_identifiers("useAuth")
    assert "useAuth" in result


def test_acronym_handler_splits() -> None:
    tokens = _tokens("HTTPSConnection")
    assert "https" in tokens
    assert "connection" in tokens
    result = split_code_identifiers("HTTPSConnection")
    assert "HTTPSConnection" in result


def test_snake_case_splits_and_keeps_original() -> None:
    result = split_code_identifiers("place_order")
    tokens = set(result.lower().split())
    assert "place" in tokens
    assert "order" in tokens
    assert "place_order" in result


def test_idempotent_token_set() -> None:
    text = "PlaceOrderRequest"
    once = set(split_code_identifiers(text).lower().split())
    twice = set(split_code_identifiers(split_code_identifiers(text)).lower().split())
    assert once == twice


def test_symbol_name_tokens_keeps_identifier_and_subwords() -> None:
    tokens = _indexed("GetWebAuthnSession")
    assert {"getwebauthnsession", "get", "web", "authn", "session"} <= tokens


def test_symbol_name_tokens_emits_suffix_joins() -> None:
    tokens = _indexed("GetWebAuthnSession")
    assert {"webauthnsession", "authnsession"} <= tokens


@pytest.mark.parametrize(
    "name,query",
    [
        # The regression this exists to prevent: queries spanning a subword
        # boundary but not anchored at the start of the identifier.
        ("GetWebAuthnSession", "WebAuth"),
        ("RemoveWebAuthnSession", "WebAuthnSess"),
        ("defaultSecurityFilterChain", "securityF"),
        ("JwtTokenCustomizerConfig", "tokenCust"),
        ("LoginBeginRequest", "BeginRe"),
        ("JpaClientRepository", "ClientRep"),
        ("NewInMemoryStore", "InMemory"),
        # Still-supported existing behaviour.
        ("GetWebAuthnSession", "GetWeb"),
        ("GetWebAuthnSession", "session"),
        ("placeOrderRequest", "ord"),
        ("place_order_request", "orderRequest"),
    ],
)
def test_subword_boundary_queries_are_index_hits(name: str, query: str) -> None:
    assert _matches(name, query)


@pytest.mark.parametrize(
    "name,query",
    [
        # Mid-token fragments are deliberately not index hits — they fall through
        # to the client-side scan in QdrantStore._find_by_name_scanning.
        ("placeOrderRequest", "rder"),
        ("GetRegisteredPasskeys", "asskey"),
        # Token semantics: "auth" does not prefix the token "oauth2".
        ("oauth2_session", "auth"),
    ],
)
def test_mid_token_fragments_are_not_index_hits(name: str, query: str) -> None:
    assert not _matches(name, query)


def test_prose_names_skip_suffix_joins() -> None:
    """Headings and selector lists are already whitespace-tokenized."""
    name = "Registration and Authentication flow"
    assert symbol_name_tokens(name) == split_code_identifiers(name)


def test_suffix_joins_are_capped() -> None:
    name = "".join(f"Part{i}" for i in range(20))
    joins = symbol_name_tokens(name).split("\n")[2].split()
    assert len(joins) <= MAX_SUFFIX_JOIN_SUBWORDS - 1


def test_single_subword_name_adds_no_joins() -> None:
    assert symbol_name_tokens("main") == split_code_identifiers("main")
