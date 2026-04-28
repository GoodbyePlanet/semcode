from __future__ import annotations

from server.parser.typescript import TypeScriptParser


def test_empty_file_returns_no_symbols():
    assert TypeScriptParser().parse_file(b"", "svc/empty.ts") == []


def test_parser_caches_ts_and_tsx_instances():
    """Parser instances must be cached, not recreated per file."""
    p = TypeScriptParser()
    assert p._ts is not None
    assert p._tsx is not None
    assert p._ts is not p._tsx


def test_cached_parser_used_across_calls():
    """parse_file must use the same parser object on repeated calls."""
    p = TypeScriptParser()
    ts_id_before = id(p._ts)
    tsx_id_before = id(p._tsx)
    p.parse_file(b"export function noop() {}", "svc/util.ts")
    p.parse_file(b"export const A = () => <div />;", "svc/A.tsx")
    assert id(p._ts) == ts_id_before
    assert id(p._tsx) == tsx_id_before


def test_canonical_react_component_fixture(read_fixture):
    src = read_fixture("typescript/Counter.tsx")
    syms = TypeScriptParser().parse_file(src, "svc/Counter.tsx")

    by_name = {s.name: s for s in syms}
    assert set(by_name) == {"CounterProps", "useCounter", "Counter"}

    assert by_name["CounterProps"].symbol_type == "interface"
    assert by_name["useCounter"].symbol_type == "react_hook"
    assert by_name["Counter"].symbol_type == "react_component"

    for s in syms:
        assert s.language == "typescript"
        assert s.file_path == "svc/Counter.tsx"
