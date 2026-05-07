from __future__ import annotations

from server.parser.kotlin import KotlinParser


def test_empty_file_returns_no_symbols():
    assert KotlinParser().parse_file(b"", "svc/Empty.kt") == []


def test_canonical_user_controller_fixture(read_fixture):
    src = read_fixture("kotlin/UserController.kt")
    syms = KotlinParser().parse_file(src, "svc/UserController.kt")

    by_name = {s.name: s for s in syms}
    assert {
        "UserController",
        "UserService",
        "User",
        "Helpers",
        "MyView",
        "getUser",
        "createUser",
        "format",
    } <= set(by_name)

    controller = by_name["UserController"]
    assert controller.symbol_type == "controller"
    assert controller.extras["base_route"] == "/users"
    assert controller.extras["stereotype"] == "controller"
    assert controller.package == "com.example.app"
    assert controller.docstring and "users" in controller.docstring.lower()

    get_user = by_name["getUser"]
    assert get_user.symbol_type == "method"
    assert get_user.parent_name == "UserController"
    assert get_user.extras["http_method"] == "GET"
    assert get_user.extras["http_route"] == "/users/{id}"
    assert get_user.extras["is_suspend"] is True

    create_user = by_name["createUser"]
    assert create_user.extras["http_method"] == "POST"

    assert by_name["UserService"].symbol_type == "interface"
    assert by_name["User"].symbol_type == "data_class"
    assert by_name["Helpers"].symbol_type == "object"

    my_view = by_name["MyView"]
    assert my_view.symbol_type == "composable"
    assert "Composable" in my_view.annotations

    fmt = by_name["format"]
    assert fmt.parent_name == "Helpers"

    for s in syms:
        assert s.language == "kotlin"
