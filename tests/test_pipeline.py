from __future__ import annotations

from server.indexer.pipeline import _build_bm25_text, _build_embedding_text
from server.parser.base import CodeSymbol


def _sym(docstring: str) -> CodeSymbol:
    return CodeSymbol(
        name="fn",
        symbol_type="function",
        language="python",
        source="def fn(): pass",
        file_path="svc/mod.py",
        start_line=1,
        end_line=1,
        docstring=docstring,
    )


def test_python_triple_double_quote_stripped():
    text = _build_embedding_text(_sym('"""Hello world"""'), "svc")
    assert "Hello world" in text
    assert '"""' not in text


def test_python_triple_single_quote_stripped():
    text = _build_embedding_text(_sym("'''Important note'''"), "svc")
    assert "Important note" in text
    assert "'''" not in text


def test_jsdoc_delimiters_stripped():
    text = _build_embedding_text(_sym("/** Does something */"), "svc")
    assert "Does something" in text
    assert "/**" not in text
    assert "*/" not in text


def test_docstring_content_not_mangled():
    """A docstring starting with a word should not lose its first char."""
    text = _build_embedding_text(_sym('"""important content"""'), "svc")
    assert "important content" in text


def test_bm25_text_contains_signature_and_source():
    sym = CodeSymbol(
        name="placeOrder",
        symbol_type="method",
        language="java",
        source="void placeOrder(PlaceOrderRequest req) {}",
        file_path="svc/Order.java",
        start_line=10,
        end_line=12,
        signature="void placeOrder(PlaceOrderRequest req)",
        docstring="Places an order.",
    )
    text = _build_bm25_text(sym)
    assert "void placeOrder(PlaceOrderRequest req)" in text
    assert "Places an order." in text
    assert "void placeOrder(PlaceOrderRequest req) {}" in text


def test_bm25_text_excludes_preamble():
    """BM25 text must not contain the narrative preamble used for dense embedding."""
    sym = CodeSymbol(
        name="placeOrder",
        symbol_type="method",
        language="java",
        source="void placeOrder() {}",
        file_path="svc/Order.java",
        start_line=1,
        end_line=3,
    )
    bm25 = _build_bm25_text(sym)
    dense = _build_embedding_text(sym, "orders-service")
    assert "Java method" in dense
    assert "Java method" not in bm25
