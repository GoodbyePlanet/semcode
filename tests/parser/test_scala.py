from __future__ import annotations

from server.parser.scala import ScalaParser


def test_empty_file_returns_no_symbols():
    assert ScalaParser().parse_file(b"", "svc/Empty.scala") == []


def test_canonical_user_controller_fixture(read_fixture):
    src = read_fixture("scala/UserController.scala")
    syms = ScalaParser().parse_file(src, "svc/UserController.scala")

    by_key = {(s.name, s.symbol_type): s for s in syms}
    assert ("UserController", "controller") in by_key
    assert ("UserService", "trait") in by_key
    assert ("UserService", "object") in by_key  # companion
    assert ("User", "case_class") in by_key
    assert ("Helpers", "object") in by_key
    assert ("show", "method") in by_key
    assert ("list", "method") in by_key
    assert ("apply", "method") in by_key
    assert ("format", "method") in by_key

    controller = by_key[("UserController", "controller")]
    assert controller.extras["superclass"] == "Controller"
    assert controller.extras["is_play_controller"] is True
    assert controller.package == "com.example.app"
    assert controller.docstring and "controller" in controller.docstring.lower()

    show = by_key[("show", "method")]
    assert show.parent_name == "UserController"

    for s in syms:
        assert s.language == "scala"
