from __future__ import annotations

from server.parser.json_parser import JsonParser


def test_empty_file_returns_single_document_symbol() -> None:
    syms = JsonParser().parse_file(b"", "svc/empty.json")
    assert len(syms) == 1
    assert syms[0].symbol_type == "document"
    assert syms[0].name == "empty.json"
    assert syms[0].extras["top_keys"] == []


def test_canonical_package_json_fixture(read_fixture) -> None:
    src = read_fixture("json/package.json")
    syms = JsonParser().parse_file(src, "svc/package.json")

    assert len(syms) == 1
    doc = syms[0]
    assert doc.symbol_type == "document"
    assert doc.name == "package.json"
    assert doc.language == "json"
    assert doc.extras["top_keys"] == ["name", "version", "scripts", "dependencies"]


def test_invalid_json_still_yields_document(read_fixture) -> None:
    syms = JsonParser().parse_file(b"{ not valid", "svc/bad.json")
    assert len(syms) == 1
    assert syms[0].extras["top_keys"] == []
