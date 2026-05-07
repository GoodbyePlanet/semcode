from __future__ import annotations

from server.parser.bash import BashParser


def test_empty_file_returns_no_symbols():
    assert BashParser().parse_file(b"", "svc/empty.sh") == []


def test_canonical_deploy_fixture(read_fixture):
    src = read_fixture("bash/deploy.sh")
    syms = BashParser().parse_file(src, "svc/deploy.sh")

    by_name = {s.name: s for s in syms}
    assert {"greet", "add"} == set(by_name)

    greet = by_name["greet"]
    assert greet.symbol_type == "function"
    assert greet.docstring and "greeting" in greet.docstring.lower()

    add = by_name["add"]
    assert add.docstring and "Add two numbers" in add.docstring

    for s in syms:
        assert s.language == "bash"
