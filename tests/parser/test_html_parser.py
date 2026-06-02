from __future__ import annotations

from server.parser.html_parser import HtmlParser


def test_empty_file_returns_single_document_symbol() -> None:
    syms = HtmlParser().parse_file(b"", "svc/empty.html")
    assert len(syms) == 1
    assert syms[0].symbol_type == "document"
    assert syms[0].name == "empty.html"


def test_canonical_page_fixture(read_fixture) -> None:
    src = read_fixture("html/page.html")
    syms = HtmlParser().parse_file(src, "svc/page.html")

    types = [s.symbol_type for s in syms]
    assert types.count("heading") == 2
    assert types.count("element") >= 2

    by_id = {s.extras.get("id"): s for s in syms if s.extras.get("id")}
    assert "page-header" in by_id
    assert "intro" in by_id

    headings = [s for s in syms if s.symbol_type == "heading"]
    assert {h.extras["tag"] for h in headings} == {"h1", "h2"}

    for s in syms:
        assert s.language == "html"
