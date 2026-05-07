from __future__ import annotations

from typing import Any

import tree_sitter_sql
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

SQL_LANGUAGE = Language(tree_sitter_sql.language())

_CREATE_TYPE_TO_SYMBOL = {
    "create_table": "table",
    "create_view": "view",
    "create_function": "function",
    "create_procedure": "procedure",
    "create_index": "index",
    "create_trigger": "trigger",
    "create_materialized_view": "materialized_view",
    "create_type": "type",
}


def _docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    lines: list[str] = []
    while prev is not None:
        if prev.type in ("comment", "marginalia"):
            lines.insert(0, _node_text(prev, source))
            prev = prev.prev_sibling
            continue
        if prev.type in ("\n", " ", ";"):
            prev = prev.prev_sibling
            continue
        break
    return "\n".join(lines) if lines else None


def _object_name(node: Node, source: bytes) -> str | None:
    for child in node.children:
        if child.type == "object_reference":
            for sub in child.children:
                if sub.type == "identifier":
                    return _node_text(sub, source)
        if child.type == "identifier":
            return _node_text(child, source)
    return None


def _signature(node: Node, source: bytes) -> str:
    text = _node_text(node, source)
    return text.split("\n", 1)[0].split("(", 1)[0].strip()


def _column_count(create_table_node: Node) -> int:
    for child in create_table_node.children:
        if child.type == "column_definitions":
            return sum(1 for c in child.children if c.type == "column_definition")
    return 0


def _parse_create(
    create_node: Node,
    statement_node: Node,
    source: bytes,
    file_path: str,
) -> CodeSymbol | None:
    sym_type = _CREATE_TYPE_TO_SYMBOL.get(create_node.type)
    if sym_type is None:
        return None
    name = _object_name(create_node, source)
    if name is None:
        return None

    extras: dict[str, Any] = {}
    if create_node.type == "create_table":
        extras["column_count"] = _column_count(create_node)

    return CodeSymbol(
        name=name,
        symbol_type=sym_type,
        language="sql",
        source=_node_text(statement_node, source),
        file_path=file_path,
        start_line=statement_node.start_point[0] + 1,
        end_line=statement_node.end_point[0] + 1,
        signature=_signature(create_node, source),
        docstring=_docstring(statement_node, source),
        extras=extras,
    )


class SqlParser:
    def __init__(self) -> None:
        self._parser = Parser(SQL_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".sql"]

    def language(self) -> str:
        return "sql"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        symbols: list[CodeSymbol] = []
        for child in tree.root_node.children:
            if child.type != "statement":
                continue
            for sub in child.children:
                if sub.type in _CREATE_TYPE_TO_SYMBOL:
                    sym = _parse_create(sub, child, source, file_path)
                    if sym:
                        symbols.append(sym)
                    break
        return symbols
