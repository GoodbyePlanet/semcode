from __future__ import annotations

import tree_sitter_go
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol

GO_LANGUAGE = Language(tree_sitter_go.language())


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _get_package(root: Node, source: bytes) -> str | None:
    for child in root.children:
        if child.type == "package_clause":
            for sub in child.children:
                if sub.type == "package_identifier":
                    return _node_text(sub, source)
    return None


def _get_doc_comment(node: Node, source: bytes) -> str | None:
    """Collect consecutive // or /* */ comments immediately preceding the node."""
    prev = node.prev_sibling
    comments: list[str] = []
    while prev is not None and prev.type == "comment":
        comments.insert(0, _node_text(prev, source))
        prev = prev.prev_sibling
    return "\n".join(comments) if comments else None


def _sig_before_body(node: Node, source: bytes) -> str:
    body = node.child_by_field_name("body")
    if body:
        return source[node.start_byte:body.start_byte].decode("utf-8", errors="replace").strip()
    return _node_text(node, source).split("{")[0].strip()


def _parse_function(node: Node, source: bytes, file_path: str, package: str | None) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None

    return CodeSymbol(
        name=_node_text(name_node, source),
        symbol_type="function",
        language="go",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        package=package,
        signature=_sig_before_body(node, source),
        docstring=_get_doc_comment(node, source),
    )


def _parse_method(node: Node, source: bytes, file_path: str, package: str | None) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None

    # Extract receiver type as parent_name, e.g. (r *Router) → "Router"
    parent_name: str | None = None
    receiver = node.child_by_field_name("receiver")
    if receiver:
        for child in receiver.children:
            if child.type == "parameter_declaration":
                type_node = child.child_by_field_name("type")
                if type_node:
                    parent_name = _node_text(type_node, source).lstrip("*")

    return CodeSymbol(
        name=_node_text(name_node, source),
        symbol_type="method",
        language="go",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        package=package,
        signature=_sig_before_body(node, source),
        docstring=_get_doc_comment(node, source),
    )


def _parse_type_declaration(
    node: Node, source: bytes, file_path: str, package: str | None
) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []
    docstring = _get_doc_comment(node, source)

    for child in node.children:
        if child.type != "type_spec":
            continue
        name_node = child.child_by_field_name("name")
        if name_node is None:
            continue

        type_value = child.child_by_field_name("type")
        if type_value is None:
            continue

        if type_value.type == "struct_type":
            sym_type = "struct"
        elif type_value.type == "interface_type":
            sym_type = "interface"
        else:
            sym_type = "type"

        symbols.append(CodeSymbol(
            name=_node_text(name_node, source),
            symbol_type=sym_type,
            language="go",
            source=_node_text(node, source),
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            package=package,
            signature=_node_text(child, source).split("{")[0].strip(),
            docstring=docstring,
        ))

    return symbols


class GoParser:
    def __init__(self) -> None:
        self._parser = Parser(GO_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".go"]

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        root = tree.root_node
        package = _get_package(root, source)
        symbols: list[CodeSymbol] = []

        for child in root.children:
            if child.type == "function_declaration":
                sym = _parse_function(child, source, file_path, package)
                if sym:
                    symbols.append(sym)
            elif child.type == "method_declaration":
                sym = _parse_method(child, source, file_path, package)
                if sym:
                    symbols.append(sym)
            elif child.type == "type_declaration":
                symbols.extend(_parse_type_declaration(child, source, file_path, package))

        return symbols
