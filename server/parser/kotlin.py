from __future__ import annotations

import re
from typing import Any

import tree_sitter_kotlin
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text
from server.parser._spring_annotations import (
    HTTP_METHOD_ANNOTATIONS,
    SPRING_STEREOTYPES,
)

KOTLIN_LANGUAGE = Language(tree_sitter_kotlin.language())


def _docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    while prev is not None:
        if prev.type in ("multiline_comment", "block_comment"):
            text = _node_text(prev, source)
            if text.startswith("/**"):
                return text
            break
        if prev.type in ("line_comment", "comment"):
            break
        if prev.type in ("\n", " "):
            prev = prev.prev_sibling
            continue
        break
    return None


def _annotation_name(annotation_node: Node, source: bytes) -> str | None:
    for child in annotation_node.children:
        if child.type == "constructor_invocation":
            for sub in child.children:
                if sub.type == "user_type":
                    for inner in sub.children:
                        if inner.type in ("identifier", "type_identifier"):
                            return _node_text(inner, source)
        if child.type == "user_type":
            for sub in child.children:
                if sub.type in ("identifier", "type_identifier"):
                    return _node_text(sub, source)
        if child.type in ("identifier", "type_identifier"):
            return _node_text(child, source)
    return None


def _annotation_first_string(annotation_node: Node, source: bytes) -> str | None:
    text = _node_text(annotation_node, source)
    m = re.search(r'"([^"]*)"', text)
    return m.group(1) if m else None


def _collect_annotations(
    modifiers: Node | None, source: bytes
) -> list[tuple[str, Node]]:
    if modifiers is None:
        return []
    out: list[tuple[str, Node]] = []
    for child in modifiers.children:
        if child.type == "annotation":
            name = _annotation_name(child, source)
            if name:
                out.append((name, child))
    return out


def _modifier_keywords(modifiers: Node | None, source: bytes) -> set[str]:
    if modifiers is None:
        return set()
    keywords: set[str] = set()
    for child in modifiers.children:
        if child.type in (
            "class_modifier",
            "function_modifier",
            "visibility_modifier",
            "inheritance_modifier",
            "member_modifier",
        ):
            keywords.add(_node_text(child, source).strip())
        elif child.type in (
            "data",
            "sealed",
            "open",
            "abstract",
            "inner",
            "enum",
            "suspend",
            "inline",
        ):
            keywords.add(_node_text(child, source).strip())
    return keywords


def _get_package(root: Node, source: bytes) -> str | None:
    for child in root.children:
        if child.type == "package_header":
            for sub in child.children:
                if sub.type == "qualified_identifier":
                    return _node_text(sub, source)
    return None


def _signature(node: Node, source: bytes) -> str:
    body = next(
        (
            c
            for c in node.children
            if c.type in ("function_body", "class_body", "block")
        ),
        None,
    )
    if body is not None:
        return (
            source[node.start_byte : body.start_byte]
            .decode("utf-8", errors="replace")
            .strip()
        )
    return _node_text(node, source).split("{", 1)[0].split("=", 1)[0].strip()


def _modifiers_node(node: Node) -> Node | None:
    for child in node.children:
        if child.type == "modifiers":
            return child
    return None


def _http_route(
    annotations: list[tuple[str, Node]],
    source: bytes,
    base_route: str | None,
) -> tuple[str | None, str | None]:
    for name, ann_node in annotations:
        if name in HTTP_METHOD_ANNOTATIONS:
            method = HTTP_METHOD_ANNOTATIONS[name] or "REQUEST"
            value = _annotation_first_string(ann_node, source) or ""
            full = (base_route or "") + value
            return method, full or None
    return None, None


def _base_route(annotations: list[tuple[str, Node]], source: bytes) -> str | None:
    for name, ann_node in annotations:
        if name == "RequestMapping":
            return _annotation_first_string(ann_node, source)
    return None


def _is_class_keyword(node: Node) -> str:
    """Return 'class' or 'interface' depending on which keyword child the declaration has."""
    for child in node.children:
        if child.type == "interface":
            return "interface"
        if child.type == "class":
            return "class"
    return "class"


def _parse_function(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    parent_name: str | None,
    base_route: str | None,
    stereotype: str | None,
) -> CodeSymbol | None:
    name_node = None
    for child in node.children:
        if child.type in ("identifier", "simple_identifier"):
            name_node = child
            break
    if name_node is None:
        return None

    modifiers = _modifiers_node(node)
    annotations = _collect_annotations(modifiers, source)
    annotation_names = [n for n, _ in annotations]
    keywords = _modifier_keywords(modifiers, source)
    http_method, http_route = _http_route(annotations, source, base_route)

    sym_type = "method" if parent_name else "function"
    if "Composable" in annotation_names:
        sym_type = "composable"

    return CodeSymbol(
        name=_node_text(name_node, source),
        symbol_type=sym_type,
        language="kotlin",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        package=package,
        annotations=annotation_names,
        signature=_signature(node, source),
        docstring=_docstring(node, source),
        extras={
            "is_suspend": "suspend" in keywords,
            "is_inline": "inline" in keywords,
            "stereotype": stereotype,
            "http_method": http_method,
            "http_route": http_route,
        },
    )


def _parse_class_or_object(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    parent_name: str | None = None,
) -> list[CodeSymbol]:
    name_node = None
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "simple_identifier"):
            name_node = child
            break
    if name_node is None:
        return []
    name = _node_text(name_node, source)

    modifiers = _modifiers_node(node)
    annotations = _collect_annotations(modifiers, source)
    annotation_names = [n for n, _ in annotations]
    keywords = _modifier_keywords(modifiers, source)
    base_route = _base_route(annotations, source)

    stereotype = next(
        (SPRING_STEREOTYPES[n] for n in annotation_names if n in SPRING_STEREOTYPES),
        None,
    )

    if node.type == "object_declaration":
        sym_type = "object"
    elif "data" in keywords:
        sym_type = "data_class"
    elif "enum" in keywords:
        sym_type = "enum"
    elif "sealed" in keywords:
        sym_type = "sealed_class"
    else:
        sym_type = stereotype or _is_class_keyword(node)

    extras: dict[str, Any] = {
        "stereotype": stereotype,
        "base_route": base_route,
        "kotlin_modifiers": sorted(keywords),
    }

    symbols: list[CodeSymbol] = [
        CodeSymbol(
            name=name,
            symbol_type=sym_type,
            language="kotlin",
            source=_node_text(node, source),
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            parent_name=parent_name,
            package=package,
            annotations=annotation_names,
            signature=_signature(node, source),
            docstring=_docstring(node, source),
            extras=extras,
        )
    ]

    body = next(
        (c for c in node.children if c.type in ("class_body", "enum_class_body")),
        None,
    )
    if body is None:
        return symbols
    for child in body.children:
        if child.type == "function_declaration":
            m = _parse_function(
                child, source, file_path, package, name, base_route, stereotype
            )
            if m:
                symbols.append(m)
        elif child.type in ("class_declaration", "object_declaration"):
            symbols.extend(
                _parse_class_or_object(
                    child, source, file_path, package, parent_name=name
                )
            )

    return symbols


def _walk(
    container: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    symbols: list[CodeSymbol],
) -> None:
    for child in container.children:
        if child.type in ("class_declaration", "object_declaration"):
            symbols.extend(_parse_class_or_object(child, source, file_path, package))
        elif child.type == "function_declaration":
            sym = _parse_function(child, source, file_path, package, None, None, None)
            if sym:
                symbols.append(sym)


class KotlinParser:
    def __init__(self) -> None:
        self._parser = Parser(KOTLIN_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".kt", ".kts"]

    def language(self) -> str:
        return "kotlin"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        root = tree.root_node
        package = _get_package(root, source)
        symbols: list[CodeSymbol] = []
        _walk(root, source, file_path, package, symbols)
        return symbols
