from __future__ import annotations

from server.parser.go import GoParser


def test_empty_file_returns_no_symbols() -> None:
    assert GoParser().parse_file(b"", "svc/empty.go") == []


def test_canonical_router_fixture(read_fixture) -> None:
    src = read_fixture("go/router.go")
    syms = GoParser().parse_file(src, "svc/router.go")

    by_name = {s.name: s for s in syms}
    assert set(by_name) == {"Router", "Handler", "NewRouter", "Handle"}

    assert by_name["Router"].symbol_type == "struct"
    assert by_name["Handler"].symbol_type == "interface"
    assert by_name["NewRouter"].symbol_type == "function"

    handle = by_name["Handle"]
    assert handle.symbol_type == "method"
    assert handle.parent_name == "Router"

    for s in syms:
        assert s.language == "go"
        assert s.package == "routing"
        assert s.file_path == "svc/router.go"
