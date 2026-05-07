from __future__ import annotations

from server.parser.csharp import CSharpParser


def test_empty_file_returns_no_symbols():
    assert CSharpParser().parse_file(b"", "svc/Empty.cs") == []


def test_canonical_user_controller_fixture(read_fixture):
    src = read_fixture("csharp/UserController.cs")
    syms = CSharpParser().parse_file(src, "svc/UserController.cs")

    # Constructor in C# shares its class's name; pick the type symbol explicitly.
    by_key = {(s.name, s.symbol_type): s for s in syms}
    assert ("UserController", "controller") in by_key
    assert ("UserController", "constructor") in by_key
    assert ("User", "record") in by_key
    assert ("IUserService", "interface") in by_key
    assert ("Status", "enum") in by_key

    by_name = {s.name: s for s in syms if s.symbol_type != "constructor"}
    controller = by_name["UserController"]
    assert controller.symbol_type == "controller"
    assert controller.docstring and "users" in controller.docstring.lower()
    assert "ApiController" in controller.annotations
    assert "Route" in controller.annotations
    assert controller.extras["base_route"] == "api/users"
    assert controller.package == "MyApp.Api.Controllers"

    get_user = by_name["GetUser"]
    assert get_user.symbol_type == "method"
    assert get_user.parent_name == "UserController"
    assert get_user.extras["http_method"] == "GET"
    assert get_user.extras["http_route"] == "api/users{id}"
    assert get_user.extras["is_async"] is True

    create_user = by_name["CreateUser"]
    assert create_user.extras["http_method"] == "POST"
    assert "Authorize" in create_user.annotations

    assert by_name["User"].symbol_type == "record"
    assert by_name["IUserService"].symbol_type == "interface"
    assert by_name["Status"].symbol_type == "enum"

    for s in syms:
        assert s.language == "csharp"
        assert s.file_path == "svc/UserController.cs"
