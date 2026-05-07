from __future__ import annotations

from server.parser.sql import SqlParser


def test_empty_file_returns_no_symbols():
    assert SqlParser().parse_file(b"", "svc/empty.sql") == []


def test_canonical_schema_fixture(read_fixture):
    src = read_fixture("sql/schema.sql")
    syms = SqlParser().parse_file(src, "svc/schema.sql")

    by_key = {(s.name, s.symbol_type): s for s in syms}
    assert ("users", "table") in by_key
    assert ("idx_users_email", "index") in by_key
    assert ("active_users", "view") in by_key

    users = by_key[("users", "table")]
    assert users.extras["column_count"] == 3
    assert users.docstring and "Users table" in users.docstring

    for s in syms:
        assert s.language == "sql"
