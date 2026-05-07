from __future__ import annotations

from server.parser.ruby import RubyParser


def test_empty_file_returns_no_symbols():
    assert RubyParser().parse_file(b"", "svc/empty.rb") == []


def test_canonical_users_controller_fixture(read_fixture):
    src = read_fixture("ruby/users_controller.rb")
    syms = RubyParser().parse_file(src, "svc/users_controller.rb")

    by_name = {s.name: s for s in syms}
    assert {
        "UsersController",
        "User",
        "Helpers",
        "show",
        "create_default",
        "format",
    } <= set(by_name)

    controller = by_name["UsersController"]
    assert controller.symbol_type == "controller"
    assert controller.extras["rails_kind"] == "controller"
    assert controller.extras["superclass"] == "ApplicationController"
    assert "before_action" in controller.extras["dsl_calls"]
    assert "has_many" in controller.extras["dsl_calls"]
    assert controller.docstring and "users" in controller.docstring.lower()

    user = by_name["User"]
    assert user.symbol_type == "model"
    assert "validates" in user.extras["dsl_calls"]

    assert by_name["Helpers"].symbol_type == "module"

    show = by_name["show"]
    assert show.symbol_type == "method"
    assert show.parent_name == "UsersController"

    create_default = by_name["create_default"]
    assert create_default.symbol_type == "class_method"

    fmt = by_name["format"]
    assert fmt.symbol_type == "class_method"
    assert fmt.parent_name == "Helpers"

    for s in syms:
        assert s.language == "ruby"
