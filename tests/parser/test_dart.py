from __future__ import annotations

from server.parser.dart import DartParser


def test_empty_file_returns_no_symbols():
    assert DartParser().parse_file(b"", "svc/empty.dart") == []


def test_canonical_user_widget_fixture(read_fixture):
    src = read_fixture("dart/user_widget.dart")
    syms = DartParser().parse_file(src, "svc/user_widget.dart")

    by_key = {(s.name, s.symbol_type): s for s in syms}
    assert ("UserWidget", "widget") in by_key
    assert ("CounterState", "widget") in by_key
    assert ("Logging", "mixin") in by_key
    assert ("Status", "enum") in by_key
    assert ("StringX", "extension") in by_key
    assert ("helper", "function") in by_key
    assert ("build", "method") in by_key
    assert ("increment", "method") in by_key
    assert ("log", "method") in by_key
    assert ("reversed", "method") in by_key

    user_widget = by_key[("UserWidget", "widget")]
    assert user_widget.extras["is_flutter_widget"] is True
    assert user_widget.extras["superclass"] == "StatelessWidget"
    assert user_widget.docstring and "user widget" in user_widget.docstring.lower()

    build = by_key[("build", "method")]
    assert build.parent_name == "UserWidget"
    assert "override" in build.annotations

    for s in syms:
        assert s.language == "dart"
