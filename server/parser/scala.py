from __future__ import annotations

from typing import Any

import tree_sitter_scala
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

SCALA_LANGUAGE = Language(tree_sitter_scala.language())

_PLAY_BASES = {"Controller", "BaseController", "AbstractController"}


def _docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    while prev is not None:
        if prev.type == "block_comment":
            text = _node_text(prev, source)
            if text.startswith("/**"):
                return text
            break
        if prev.type in ("\n", " "):
            prev = prev.prev_sibling
            continue
        break
    return None


def _get_package(root: Node, source: bytes) -> str | None:
    for child in root.children:
        if child.type == "package_clause":
            name_node = child.child_by_field_name("name")
            if name_node:
                return _node_text(name_node, source)
            for sub in child.children:
                if sub.type == "package_identifier":
                    return _node_text(sub, source)
    return None


def _signature(node: Node, source: bytes) -> str:
    body = next(
        (c for c in node.children if c.type in ("template_body", "block")),
        None,
    )
    if body is not None:
        return (
            source[node.start_byte : body.start_byte]
            .decode("utf-8", errors="replace")
            .strip()
        )
    return _node_text(node, source).split("\n", 1)[0].strip()


def _extends_name(node: Node, source: bytes) -> str | None:
    for child in node.children:
        if child.type == "extends_clause":
            for sub in child.children:
                if sub.type in ("type_identifier", "compound_type"):
                    return _node_text(sub, source).split()[0]
    return None


def _collect_annotations(node: Node, source: bytes) -> list[str]:
    annotations: list[str] = []
    for child in node.children:
        if child.type == "annotation":
            name_node = child.child_by_field_name("name")
            if name_node:
                annotations.append(_node_text(name_node, source))
            else:
                for sub in child.children:
                    if sub.type == "type_identifier":
                        annotations.append(_node_text(sub, source))
                        break
    return annotations


def _is_case_class(node: Node) -> bool:
    return any(c.type == "case" for c in node.children)


def _parse_function(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    parent_name: str | None,
) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None

    annotations = _collect_annotations(node, source)
    sym_type = "method" if parent_name else "function"

    return CodeSymbol(
        name=_node_text(name_node, source),
        symbol_type=sym_type,
        language="scala",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        package=package,
        annotations=annotations,
        signature=_signature(node, source),
        docstring=_docstring(node, source),
    )


_TYPE_NODE_TO_BASE_SYMBOL = {
    "class_definition": "class",
    "trait_definition": "trait",
    "object_definition": "object",
}


def _parse_type_decl(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    parent_name: str | None = None,
) -> list[CodeSymbol]:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return []
    name = _node_text(name_node, source)

    annotations = _collect_annotations(node, source)
    superclass = _extends_name(node, source)
    is_play = superclass in _PLAY_BASES if superclass else False

    base_sym = _TYPE_NODE_TO_BASE_SYMBOL.get(node.type, "class")
    if base_sym == "class" and _is_case_class(node):
        sym_type = "case_class"
    elif is_play:
        sym_type = "controller"
    else:
        sym_type = base_sym

    extras: dict[str, Any] = {
        "superclass": superclass,
        "is_play_controller": is_play,
    }

    symbols: list[CodeSymbol] = [
        CodeSymbol(
            name=name,
            symbol_type=sym_type,
            language="scala",
            source=_node_text(node, source),
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            parent_name=parent_name,
            package=package,
            annotations=annotations,
            signature=_signature(node, source),
            docstring=_docstring(node, source),
            extras=extras,
        )
    ]

    body = next((c for c in node.children if c.type == "template_body"), None)
    if body is None:
        return symbols
    for child in body.children:
        if child.type in ("function_definition", "function_declaration"):
            m = _parse_function(child, source, file_path, package, name)
            if m:
                symbols.append(m)
        elif child.type in _TYPE_NODE_TO_BASE_SYMBOL:
            symbols.extend(_parse_type_decl(child, source, file_path, package, name))

    return symbols


def _walk(
    container: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    symbols: list[CodeSymbol],
) -> None:
    for child in container.children:
        if child.type in _TYPE_NODE_TO_BASE_SYMBOL:
            symbols.extend(_parse_type_decl(child, source, file_path, package))
        elif child.type in ("function_definition", "function_declaration"):
            sym = _parse_function(child, source, file_path, package, None)
            if sym:
                symbols.append(sym)


class ScalaParser:
    def __init__(self) -> None:
        self._parser = Parser(SCALA_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".scala", ".sc"]

    def language(self) -> str:
        return "scala"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        root = tree.root_node
        package = _get_package(root, source)
        symbols: list[CodeSymbol] = []
        _walk(root, source, file_path, package, symbols)
        return symbols
