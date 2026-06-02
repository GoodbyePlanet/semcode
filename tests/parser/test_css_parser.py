from __future__ import annotations

from server.parser.css_parser import CssParser


def test_empty_file_returns_single_document_symbol() -> None:
    syms = CssParser().parse_file(b"", "svc/empty.css")
    assert len(syms) == 1
    assert syms[0].symbol_type == "document"
    assert syms[0].name == "empty.css"


def test_canonical_styles_fixture(read_fixture) -> None:
    src = read_fixture("css/styles.css")
    syms = CssParser().parse_file(src, "svc/styles.css")

    names = [s.name for s in syms]
    assert names == ["body", ".button", ".button:hover"]

    for s in syms:
        assert s.symbol_type == "rule"
        assert s.language == "css"

    body_rule = syms[0]
    assert "margin" in body_rule.extras["properties"]
    assert "padding" in body_rule.extras["properties"]
    assert "font-family" in body_rule.extras["properties"]
