from __future__ import annotations

from server.parser.c import CParser


def test_empty_file_returns_no_symbols():
    assert CParser().parse_file(b"", "svc/empty.c") == []


def test_canonical_math_utils_fixture(read_fixture):
    src = read_fixture("c/math_utils.c")
    syms = CParser().parse_file(src, "svc/math_utils.c")

    by_name = {s.name: s for s in syms}
    assert {"Point", "Color", "Variant", "Id", "add", "helper"} <= set(by_name)

    assert by_name["Point"].symbol_type == "type"
    assert by_name["Color"].symbol_type == "enum"
    assert by_name["Variant"].symbol_type == "union"
    assert by_name["Id"].symbol_type == "type"

    add = by_name["add"]
    assert add.symbol_type == "function"
    assert add.docstring and "Add two integers" in add.docstring

    for s in syms:
        assert s.language == "c"
