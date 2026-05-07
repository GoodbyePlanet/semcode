from __future__ import annotations

from server.parser.markdown import MarkdownParser


def test_empty_file_returns_single_document_symbol():
    syms = MarkdownParser().parse_file(b"", "svc/empty.md")
    assert len(syms) == 1
    assert syms[0].symbol_type == "document"
    assert syms[0].name == "empty.md"


def test_canonical_readme_fixture(read_fixture):
    src = read_fixture("markdown/README.md")
    syms = MarkdownParser().parse_file(src, "svc/README.md")

    names = [s.name for s in syms]
    assert names == ["Project Title", "Installation", "Requirements", "Usage"]
    assert all(s.symbol_type == "section" for s in syms)

    levels = {s.name: s.extras["level"] for s in syms}
    assert levels == {
        "Project Title": 1,
        "Installation": 2,
        "Requirements": 3,
        "Usage": 2,
    }

    parents = {s.name: s.parent_name for s in syms}
    assert parents == {
        "Project Title": None,
        "Installation": "Project Title",
        "Requirements": "Installation",
        "Usage": "Project Title",
    }

    for s in syms:
        assert s.language == "markdown"
