from __future__ import annotations

from typing import Any

import tree_sitter_java
from tree_sitter import Language, Node, Parser

from server.parser._spring_annotations import (
    HTTP_METHOD_ANNOTATIONS as _HTTP_METHOD_ANNOTATIONS,
)
from server.parser._spring_annotations import (
    LOMBOK_ANNOTATIONS as _LOMBOK_ANNOTATIONS,
)
from server.parser._spring_annotations import (
    SPRING_STEREOTYPES as _SPRING_STEREOTYPES,
)
from server.parser.base import CodeSymbol, _node_text

JAVA_LANGUAGE = Language(tree_sitter_java.language())


def _get_annotations(modifiers_node: Node | None, source: bytes) -> list[str]:
    if modifiers_node is None:
        return []
    annotations = []
    for child in modifiers_node.children:
        if child.type in ("marker_annotation", "annotation"):
            name_node = child.child_by_field_name("name")
            if name_node:
                annotations.append(_node_text(name_node, source))
    return annotations


def _get_docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    while prev and prev.type in ("", "\n", " "):
        prev = prev.prev_sibling
    if prev and prev.type == "block_comment":
        text = _node_text(prev, source)
        if text.startswith("/**"):
            return text
    return None


def _extract_annotation_value(annotation_node: Node, source: bytes) -> str | None:
    args = annotation_node.child_by_field_name("arguments")
    if not args:
        return None
    for child in args.children:
        if child.type == "string_literal":
            return _node_text(child, source).strip('"')
        if child.type == "element_value_pair":
            key = child.child_by_field_name("key")
            val = child.child_by_field_name("value")
            if key and _node_text(key, source) == "value" and val:
                return _node_text(val, source).strip('"')
    return None


def _get_package(tree_root: Node, source: bytes) -> str | None:
    for child in tree_root.children:
        if child.type == "package_declaration":
            for sub in child.children:
                if sub.type in ("scoped_identifier", "identifier"):
                    return _node_text(sub, source)
    return None


def _get_base_route(
    class_node: Node, source: bytes, annotations: list[str]
) -> str | None:
    modifiers = class_node.child_by_field_name("modifiers")
    if modifiers is None:
        return None
    for child in modifiers.children:
        if child.type == "annotation":
            name_node = child.child_by_field_name("name")
            if name_node and _node_text(name_node, source) == "RequestMapping":
                return _extract_annotation_value(child, source)
    return None


def _parse_class(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    parent_name: str | None = None,
) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []

    modifiers = node.child_by_field_name("modifiers")
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return []

    class_name = _node_text(name_node, source)
    annotations = _get_annotations(modifiers, source)

    spring_stereotype = next(
        (_SPRING_STEREOTYPES[a] for a in annotations if a in _SPRING_STEREOTYPES), None
    )
    lombok_annotations = [a for a in annotations if a in _LOMBOK_ANNOTATIONS]
    base_route = _get_base_route(node, source, annotations)

    # Build signature line
    sig_parts = []
    if modifiers:
        mods = [
            _node_text(c, source)
            for c in modifiers.children
            if c.type not in ("marker_annotation", "annotation")
        ]
        sig_parts.extend(mods)
    sig_parts.append(
        {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "record_declaration": "record",
        }.get(node.type, "class")
    )
    sig_parts.append(class_name)

    superclass = node.child_by_field_name("superclass")
    if superclass:
        sig_parts.append("extends")
        sig_parts.append(_node_text(superclass, source).replace("extends ", "").strip())

    interfaces = node.child_by_field_name("interfaces")
    if interfaces:
        sig_parts.append("implements")
        sig_parts.append(
            _node_text(interfaces, source).replace("implements ", "").strip()
        )

    signature = " ".join(sig_parts)
    docstring = _get_docstring(node, source)
    symbol_src = _node_text(node, source)

    extras: dict[str, Any] = {
        "spring_stereotype": spring_stereotype,
        "lombok_annotations": lombok_annotations,
        "base_route": base_route,
    }

    sym_type = {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "record_declaration": "record",
    }.get(node.type, "class")

    class_symbol = CodeSymbol(
        name=class_name,
        symbol_type=sym_type,
        language="java",
        source=symbol_src,
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        package=package,
        annotations=annotations,
        signature=signature,
        docstring=docstring,
        extras=extras,
    )
    symbols.append(class_symbol)

    # Parse methods within this class
    body = node.child_by_field_name("body")
    if body:
        for child in body.children:
            if child.type == "method_declaration":
                method = _parse_method(
                    child,
                    source,
                    file_path,
                    package,
                    class_name,
                    base_route,
                    spring_stereotype,
                )
                if method:
                    symbols.append(method)
            elif child.type == "constructor_declaration":
                ctor = _parse_method(
                    child,
                    source,
                    file_path,
                    package,
                    class_name,
                    base_route,
                    spring_stereotype,
                )
                if ctor:
                    symbols.append(ctor)
            elif child.type in (
                "class_declaration",
                "interface_declaration",
                "enum_declaration",
                "record_declaration",
            ):
                # Inner class
                symbols.extend(
                    _parse_class(
                        child, source, file_path, package, parent_name=class_name
                    )
                )

    return symbols


def _parse_method(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    parent_name: str,
    base_route: str | None,
    spring_stereotype: str | None,
) -> CodeSymbol | None:
    modifiers = node.child_by_field_name("modifiers")
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None

    method_name = _node_text(name_node, source)
    annotations = _get_annotations(modifiers, source)
    docstring = _get_docstring(node, source)

    # Detect HTTP method and route
    http_method = None
    http_route = None
    for ann_node in (node.child_by_field_name("modifiers") or node).children:
        if ann_node.type not in ("marker_annotation", "annotation"):
            continue
        ann_name_node = ann_node.child_by_field_name("name")
        if not ann_name_node:
            continue
        ann_name = _node_text(ann_name_node, source)
        if ann_name in _HTTP_METHOD_ANNOTATIONS:
            http_method = _HTTP_METHOD_ANNOTATIONS[ann_name] or "REQUEST"
            route_part = _extract_annotation_value(ann_node, source) or ""
            http_route = (base_route or "") + route_part

    # Build signature
    sig = _node_text(node, source).split("{")[0].strip()

    sym_type = "constructor" if node.type == "constructor_declaration" else "method"

    return CodeSymbol(
        name=method_name,
        symbol_type=sym_type,
        language="java",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        package=package,
        annotations=annotations,
        signature=sig,
        docstring=docstring,
        extras={
            "spring_stereotype": spring_stereotype,
            "http_method": http_method,
            "http_route": http_route,
        },
    )


class JavaParser:
    def __init__(self) -> None:
        self._parser = Parser(JAVA_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".java"]

    def language(self) -> str:
        return "java"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        root = tree.root_node
        package = _get_package(root, source)
        symbols: list[CodeSymbol] = []

        for child in root.children:
            if child.type in (
                "class_declaration",
                "interface_declaration",
                "enum_declaration",
                "record_declaration",
            ):
                symbols.extend(_parse_class(child, source, file_path, package))

        return symbols
