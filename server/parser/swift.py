from __future__ import annotations

from typing import Any

import tree_sitter_swift
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

SWIFT_LANGUAGE = Language(tree_sitter_swift.language())


def _docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    lines: list[str] = []
    while prev is not None:
        if prev.type == "comment":
            text = _node_text(prev, source)
            if text.startswith("///"):
                lines.insert(0, text)
                prev = prev.prev_sibling
                continue
            if text.startswith("/**"):
                lines.insert(0, text)
                break
            break
        if prev.type in ("\n", " "):
            prev = prev.prev_sibling
            continue
        break
    return "\n".join(lines) if lines else None


def _signature(node: Node, source: bytes) -> str:
    body = next(
        (
            c
            for c in node.children
            if c.type
            in (
                "function_body",
                "class_body",
                "protocol_body",
                "enum_class_body",
                "computed_property",
            )
        ),
        None,
    )
    if body is not None:
        return (
            source[node.start_byte : body.start_byte]
            .decode("utf-8", errors="replace")
            .strip()
        )
    return _node_text(node, source).split("\n", 1)[0].strip()


def _property_wrappers(node: Node, source: bytes) -> list[str]:
    wrappers: list[str] = []
    for child in node.children:
        if child.type == "modifiers":
            text = _node_text(child, source)
            for chunk in text.split():
                if chunk.startswith("@"):
                    wrappers.append(chunk[1:].split("(")[0])
    return wrappers


def _has_modifier(node: Node, source: bytes, keyword: str) -> bool:
    for child in node.children:
        if child.type == keyword:
            return True
    text = _node_text(node, source)
    return f" {keyword} " in text or text.startswith(f"{keyword} ")


def _kind_keyword(node: Node) -> str:
    """Inspect class_declaration's first non-modifier child to find the keyword."""
    for child in node.children:
        if child.type in ("struct", "class", "enum", "extension", "actor", "protocol"):
            return child.type
    return "class"


def _name(node: Node, source: bytes) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node:
        return _node_text(name_node, source).split(".")[-1]
    for child in node.children:
        if child.type == "type_identifier":
            return _node_text(child, source)
        if child.type == "simple_identifier":
            return _node_text(child, source)
    return None


def _inheritance_names(node: Node, source: bytes) -> list[str]:
    out: list[str] = []
    for child in node.children:
        if child.type == "inheritance_specifier":
            for sub in child.children:
                if sub.type == "user_type":
                    for inner in sub.children:
                        if inner.type == "type_identifier":
                            out.append(_node_text(inner, source))
                            break
    return out


def _function_async_throws(node: Node, source: bytes) -> tuple[bool, bool]:
    is_async = False
    throws = False
    for child in node.children:
        if child.type == "async":
            is_async = True
        elif child.type == "throws":
            throws = True
    return is_async, throws


def _parse_function(
    node: Node,
    source: bytes,
    file_path: str,
    parent_name: str | None,
) -> CodeSymbol | None:
    name = _name(node, source)
    if name is None:
        return None

    is_async, throws = _function_async_throws(node, source)
    annotations = _property_wrappers(node, source)

    sym_type = "method" if parent_name else "function"

    return CodeSymbol(
        name=name,
        symbol_type=sym_type,
        language="swift",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        annotations=annotations,
        signature=_signature(node, source),
        docstring=_docstring(node, source),
        extras={
            "is_async": is_async,
            "throws": throws,
            "is_objc": "objc" in annotations,
        },
    )


def _parse_type(
    node: Node,
    source: bytes,
    file_path: str,
    parent_name: str | None = None,
) -> list[CodeSymbol]:
    name = _name(node, source)
    if name is None:
        return []

    annotations = _property_wrappers(node, source)
    inheritance = _inheritance_names(node, source)
    keyword = _kind_keyword(node)

    if keyword == "extension":
        sym_type = "extension"
    elif keyword == "protocol" or node.type == "protocol_declaration":
        sym_type = "protocol"
    elif keyword == "enum":
        sym_type = "enum"
    elif keyword == "struct" and "View" in inheritance:
        sym_type = "view"
    elif keyword == "actor":
        sym_type = "actor"
    elif keyword == "struct":
        sym_type = "struct"
    else:
        sym_type = "class"

    extras: dict[str, Any] = {
        "inheritance": inheritance,
    }

    symbols: list[CodeSymbol] = [
        CodeSymbol(
            name=name,
            symbol_type=sym_type,
            language="swift",
            source=_node_text(node, source),
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            parent_name=parent_name,
            annotations=annotations,
            signature=_signature(node, source),
            docstring=_docstring(node, source),
            extras=extras,
        )
    ]

    body = next(
        (
            c
            for c in node.children
            if c.type in ("class_body", "protocol_body", "enum_class_body")
        ),
        None,
    )
    if body is None:
        return symbols
    for child in body.children:
        if child.type in ("function_declaration", "protocol_function_declaration"):
            m = _parse_function(child, source, file_path, name)
            if m:
                symbols.append(m)
        elif child.type in ("class_declaration", "protocol_declaration"):
            symbols.extend(_parse_type(child, source, file_path, name))

    return symbols


def _walk(
    container: Node,
    source: bytes,
    file_path: str,
    symbols: list[CodeSymbol],
) -> None:
    for child in container.children:
        if child.type in ("class_declaration", "protocol_declaration"):
            symbols.extend(_parse_type(child, source, file_path))
        elif child.type == "function_declaration":
            sym = _parse_function(child, source, file_path, None)
            if sym:
                symbols.append(sym)


class SwiftParser:
    def __init__(self) -> None:
        self._parser = Parser(SWIFT_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".swift"]

    def language(self) -> str:
        return "swift"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        symbols: list[CodeSymbol] = []
        _walk(tree.root_node, source, file_path, symbols)
        return symbols
