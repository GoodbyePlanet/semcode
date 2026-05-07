from __future__ import annotations

from server.parser.r import RParser


def test_empty_file_returns_no_symbols():
    assert RParser().parse_file(b"", "svc/empty.R") == []


def test_canonical_utils_fixture(read_fixture):
    src = read_fixture("r/utils.R")
    syms = RParser().parse_file(src, "svc/utils.R")

    by_key = {(s.name, s.symbol_type): s for s in syms}
    assert ("add", "function") in by_key
    assert ("helper", "function") in by_key
    assert ("Point", "class") in by_key
    assert ("describe", "generic") in by_key

    add = by_key[("add", "function")]
    assert add.docstring and "sum of two numbers" in add.docstring.lower()

    for s in syms:
        assert s.language == "r"
