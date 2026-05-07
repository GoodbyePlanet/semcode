from __future__ import annotations

import tree_sitter_c
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

C_LANGUAGE = Language(tree_sitter_c.language())


def _docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    while prev is not None:
        if prev.type == "comment":
            text = _node_text(prev, source)
            if text.startswith("/**") or text.startswith("///"):
                return text
            break
        if prev.type in ("\n", " "):
            prev = prev.prev_sibling
            continue
        break
    return None


def _function_name(declarator: Node, source: bytes) -> str | None:
    """Drill through pointer/parenthesized declarators to the bare identifier."""
    while declarator is not None:
        if declarator.type == "function_declarator":
            inner = declarator.child_by_field_name("declarator")
            if inner is None:
                return None
            declarator = inner
            continue
        if declarator.type in ("identifier", "field_identifier"):
            return _node_text(declarator, source)
        if declarator.type == "destructor_name":
            for child in declarator.children:
                if child.type == "identifier":
                    return "~" + _node_text(child, source)
            return None
        # pointer_declarator, parenthesized_declarator, …
        inner = declarator.child_by_field_name("declarator")
        if inner is None:
            return None
        declarator = inner
    return None


def _signature(node: Node, source: bytes) -> str:
    body = node.child_by_field_name("body")
    if body:
        return (
            source[node.start_byte : body.start_byte]
            .decode("utf-8", errors="replace")
            .strip()
        )
    return _node_text(node, source).split("{", 1)[0].split(";", 1)[0].strip()


def _parse_function(
    node: Node,
    source: bytes,
    file_path: str,
    language: str,
    parent_name: str | None = None,
    package: str | None = None,
) -> CodeSymbol | None:
    declarator = node.child_by_field_name("declarator")
    if declarator is None:
        return None
    name = _function_name(declarator, source)
    if name is None:
        return None

    sym_type = "method" if parent_name else "function"

    return CodeSymbol(
        name=name,
        symbol_type=sym_type,
        language=language,
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        package=package,
        signature=_signature(node, source),
        docstring=_docstring(node, source),
    )


def _parse_typedef(
    node: Node, source: bytes, file_path: str, language: str
) -> CodeSymbol | None:
    declarator = node.child_by_field_name("declarator")
    if declarator is None:
        return None
    name = _function_name(declarator, source)
    if name is None:
        # typedef sometimes has identifier directly
        for child in node.children:
            if child.type == "type_identifier":
                name = _node_text(child, source)
                break
    if not name:
        return None

    return CodeSymbol(
        name=name,
        symbol_type="type",
        language=language,
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=_node_text(node, source).split(";", 1)[0].strip(),
        docstring=_docstring(node, source),
    )


_TYPED_NAMED_NODE = {
    "struct_specifier": "struct",
    "enum_specifier": "enum",
    "union_specifier": "union",
}


def _parse_named_type(
    node: Node, source: bytes, file_path: str, language: str
) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return CodeSymbol(
        name=_node_text(name_node, source),
        symbol_type=_TYPED_NAMED_NODE[node.type],
        language=language,
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=_node_text(node, source).split("{", 1)[0].strip(),
        docstring=_docstring(node, source),
    )


def _walk_c(
    container: Node,
    source: bytes,
    file_path: str,
    symbols: list[CodeSymbol],
) -> None:
    for child in container.children:
        if child.type == "function_definition":
            sym = _parse_function(child, source, file_path, "c")
            if sym:
                symbols.append(sym)
        elif child.type in _TYPED_NAMED_NODE:
            sym = _parse_named_type(child, source, file_path, "c")
            if sym:
                symbols.append(sym)
        elif child.type == "type_definition":
            sym = _parse_typedef(child, source, file_path, "c")
            if sym:
                symbols.append(sym)


class CParser:
    def __init__(self) -> None:
        self._parser = Parser(C_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".c", ".h"]

    def language(self) -> str:
        return "c"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        symbols: list[CodeSymbol] = []
        _walk_c(tree.root_node, source, file_path, symbols)
        return symbols
