from __future__ import annotations

from server.parser.swift import SwiftParser


def test_empty_file_returns_no_symbols():
    assert SwiftParser().parse_file(b"", "svc/Empty.swift") == []


def test_canonical_user_view_fixture(read_fixture):
    src = read_fixture("swift/UserView.swift")
    syms = SwiftParser().parse_file(src, "svc/UserView.swift")

    by_key = {(s.name, s.symbol_type): s for s in syms}
    assert ("UserView", "view") in by_key
    assert ("UserService", "class") in by_key
    assert ("UserRepository", "protocol") in by_key
    assert ("Status", "enum") in by_key
    assert ("String", "extension") in by_key
    assert ("helper", "function") in by_key
    assert ("handleTap", "method") in by_key
    assert ("fetch", "method") in by_key
    assert ("find", "method") in by_key

    user_view = by_key[("UserView", "view")]
    assert "View" in user_view.extras["inheritance"]
    assert user_view.docstring and "user view" in user_view.docstring.lower()

    fetch = by_key[("fetch", "method")]
    assert fetch.parent_name == "UserService"
    assert fetch.extras["is_async"] is True
    assert fetch.extras["throws"] is True

    legacy = by_key[("legacyMethod", "method")]
    assert legacy.extras["is_objc"] is True
    assert "objc" in legacy.annotations

    for s in syms:
        assert s.language == "swift"
