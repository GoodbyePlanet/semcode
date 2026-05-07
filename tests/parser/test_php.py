from __future__ import annotations

from server.parser.php import PhpParser


def test_empty_file_returns_no_symbols():
    assert PhpParser().parse_file(b"<?php", "svc/empty.php") == []


def test_canonical_user_controller_fixture(read_fixture):
    src = read_fixture("php/UserController.php")
    syms = PhpParser().parse_file(src, "svc/UserController.php")

    by_name = {s.name: s for s in syms}
    assert {
        "UserController",
        "UserService",
        "HasTimestamps",
        "Status",
        "helper",
        "show",
        "store",
    } <= set(by_name)

    controller = by_name["UserController"]
    assert controller.symbol_type == "controller"
    assert controller.extras["superclass"] == "Controller"
    assert controller.extras["base_route"] == "/users"
    assert controller.docstring and "users" in controller.docstring.lower()
    assert controller.package == "App.Http.Controllers"

    show = by_name["show"]
    assert show.symbol_type == "method"
    assert show.parent_name == "UserController"
    assert show.extras["http_method"] == "GET"
    assert show.extras["http_route"] == "/users/{id}"

    store = by_name["store"]
    assert store.extras["http_method"] == "POST"
    assert store.extras["http_route"] == "/users/"

    assert by_name["UserService"].symbol_type == "interface"
    assert by_name["HasTimestamps"].symbol_type == "trait"
    assert by_name["Status"].symbol_type == "enum"
    assert by_name["helper"].symbol_type == "function"

    for s in syms:
        assert s.language == "php"
