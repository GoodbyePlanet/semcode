from __future__ import annotations

import tree_sitter_lua
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

LUA_LANGUAGE = Language(tree_sitter_lua.language())


def _docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    lines: list[str] = []
    while prev is not None:
        if prev.type == "comment":
            lines.insert(0, _node_text(prev, source))
            prev = prev.prev_sibling
            continue
        if prev.type in ("\n", " "):
            prev = prev.prev_sibling
            continue
        break
    return "\n".join(lines) if lines else None


def _signature(node: Node, source: bytes) -> str:
    text = _node_text(node, source)
    body_idx = text.find("\n")
    if body_idx > 0:
        return text[:body_idx].rstrip()
    return text.split("end", 1)[0].strip()


def _parse_function(node: Node, source: bytes, file_path: str) -> CodeSymbol | None:
    name = None
    parent_name: str | None = None

    for child in node.children:
        if child.type == "identifier":
            name = _node_text(child, source)
            break
        if child.type == "dot_index_expression":
            ids = [c for c in child.children if c.type == "identifier"]
            if len(ids) >= 2:
                parent_name = _node_text(ids[0], source)
                name = _node_text(ids[-1], source)
            break
        if child.type == "method_index_expression":
            ids = [c for c in child.children if c.type == "identifier"]
            if len(ids) >= 2:
                parent_name = _node_text(ids[0], source)
                name = _node_text(ids[-1], source)
            break

    if name is None:
        return None

    sym_type = "method" if parent_name else "function"

    return CodeSymbol(
        name=name,
        symbol_type=sym_type,
        language="lua",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        signature=_signature(node, source),
        docstring=_docstring(node, source),
    )


class LuaParser:
    def __init__(self) -> None:
        self._parser = Parser(LUA_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".lua"]

    def language(self) -> str:
        return "lua"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        symbols: list[CodeSymbol] = []
        for child in tree.root_node.children:
            if child.type in ("function_declaration", "function_definition"):
                sym = _parse_function(child, source, file_path)
                if sym:
                    symbols.append(sym)
        return symbols
