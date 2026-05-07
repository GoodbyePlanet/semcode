from __future__ import annotations

from server.parser.cpp import CppParser


def test_empty_file_returns_no_symbols():
    assert CppParser().parse_file(b"", "svc/empty.cpp") == []


def test_canonical_widgets_fixture(read_fixture):
    src = read_fixture("cpp/widgets.cpp")
    syms = CppParser().parse_file(src, "svc/widgets.cpp")

    by_key = {(s.name, s.symbol_type): s for s in syms}
    assert ("Button", "class") in by_key
    assert ("Container", "class") in by_key
    assert ("Inner", "class") in by_key
    assert ("helper", "function") in by_key
    assert ("render", "method") in by_key
    assert ("defaultWidth", "method") in by_key

    button = by_key[("Button", "class")]
    assert button.package == "ui::widgets"
    assert button.docstring and "clickable button" in button.docstring.lower()

    render = by_key[("render", "method")]
    assert render.parent_name == "Button"
    assert render.docstring and "Render the widget" in render.docstring

    container = by_key[("Container", "class")]
    assert container.extras.get("is_template") is True

    inner = by_key[("Inner", "class")]
    assert inner.package == "other"

    for s in syms:
        assert s.language == "cpp"
