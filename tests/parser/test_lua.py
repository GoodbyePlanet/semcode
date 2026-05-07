from __future__ import annotations

from server.parser.lua import LuaParser


def test_empty_file_returns_no_symbols():
    assert LuaParser().parse_file(b"", "svc/empty.lua") == []


def test_canonical_utils_fixture(read_fixture):
    src = read_fixture("lua/utils.lua")
    syms = LuaParser().parse_file(src, "svc/utils.lua")

    by_key = {(s.name, s.symbol_type, s.parent_name): s for s in syms}
    assert ("greet", "function", None) in by_key
    assert ("helper", "function", None) in by_key
    assert ("add", "method", "M") in by_key
    assert ("method", "method", "M") in by_key

    greet = by_key[("greet", "function", None)]
    assert greet.docstring and "Greets" in greet.docstring

    for s in syms:
        assert s.language == "lua"
