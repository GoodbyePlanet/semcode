from __future__ import annotations

from server.parser.rust import RustParser


def test_empty_file_returns_no_symbols():
    assert RustParser().parse_file(b"", "svc/empty.rs") == []


def test_canonical_handlers_fixture(read_fixture):
    src = read_fixture("rust/handlers.rs")
    syms = RustParser().parse_file(src, "svc/handlers.rs")

    by_name = {s.name: s for s in syms}
    assert {
        "User",
        "Authenticator",
        "Status",
        "UserId",
        "new",
        "fetch",
        "get_user",
        "create_user",
        "helper",
    } <= set(by_name)

    user = by_name["User"]
    assert user.symbol_type == "struct"
    assert user.docstring and "user record" in user.docstring.lower()
    assert "Debug" in user.extras["derive_macros"]
    assert "Serialize" in user.extras["derive_macros"]

    assert by_name["Authenticator"].symbol_type == "trait"
    assert by_name["Status"].symbol_type == "enum"
    assert by_name["UserId"].symbol_type == "type"

    new_method = by_name["new"]
    assert new_method.symbol_type == "method"
    assert new_method.parent_name == "User"
    assert new_method.docstring is not None

    fetch = by_name["fetch"]
    assert fetch.symbol_type == "method"
    assert fetch.parent_name == "User"
    assert fetch.extras["is_async"] is True

    get_user = by_name["get_user"]
    assert get_user.symbol_type == "function"
    assert get_user.extras["http_method"] == "GET"
    assert get_user.extras["http_route"] == "/users/{id}"
    assert get_user.extras["is_async"] is True

    create_user = by_name["create_user"]
    assert create_user.extras["http_method"] == "POST"
    assert create_user.extras["http_route"] == "/users"

    helper = by_name["helper"]
    assert helper.symbol_type == "function"
    assert helper.extras["is_async"] is False

    for s in syms:
        assert s.language == "rust"
        assert s.file_path == "svc/handlers.rs"
