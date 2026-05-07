from __future__ import annotations

import tree_sitter_bash
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

BASH_LANGUAGE = Language(tree_sitter_bash.language())


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


def _parse_function(node: Node, source: bytes, file_path: str) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        for child in node.children:
            if child.type == "word":
                name_node = child
                break
    if name_node is None:
        return None

    return CodeSymbol(
        name=_node_text(name_node, source),
        symbol_type="function",
        language="bash",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=_node_text(node, source).split("{", 1)[0].strip(),
        docstring=_docstring(node, source),
    )


class BashParser:
    def __init__(self) -> None:
        self._parser = Parser(BASH_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".sh", ".bash"]

    def language(self) -> str:
        return "bash"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        symbols: list[CodeSymbol] = []
        for child in tree.root_node.children:
            if child.type == "function_definition":
                sym = _parse_function(child, source, file_path)
                if sym:
                    symbols.append(sym)
        return symbols
