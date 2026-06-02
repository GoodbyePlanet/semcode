from __future__ import annotations

from server.parser.java import JavaParser


def test_empty_file_returns_no_symbols() -> None:
    assert JavaParser().parse_file(b"", "svc/Empty.java") == []


def test_canonical_user_controller_fixture(read_fixture) -> None:
    """Locks in the current parser snapshot.

    Note: today the Java parser does not surface class- or method-level
    annotations (Spring stereotypes, HTTP mappings). This test pins that
    behavior so a future fix can update the fixture intentionally.
    """
    src = read_fixture("java/UserController.java")
    syms = JavaParser().parse_file(src, "svc/UserController.java")

    types = [(s.name, s.symbol_type) for s in syms]
    assert ("UserController", "class") in types
    assert ("UserController", "constructor") in types
    assert ("get", "method") in types
    assert ("create", "method") in types

    cls = next(s for s in syms if s.symbol_type == "class")
    assert cls.package == "com.example.users"
    assert cls.parent_name is None
    assert cls.annotations == []
    assert cls.extras == {
        "spring_stereotype": None,
        "lombok_annotations": [],
        "base_route": None,
    }

    get_method = next(s for s in syms if s.name == "get" and s.symbol_type == "method")
    assert get_method.parent_name == "UserController"
    assert get_method.annotations == []
    assert get_method.extras["http_method"] is None
    assert get_method.extras["http_route"] is None

    for s in syms:
        assert s.language == "java"
