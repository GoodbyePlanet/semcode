from __future__ import annotations

import re
from typing import Any

import tree_sitter_rust
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

RUST_LANGUAGE = Language(tree_sitter_rust.language())

_HTTP_ATTRIBUTE_NAMES = {"get", "post", "put", "delete", "patch", "head", "options"}


def _collect_preceding(
    node: Node, source: bytes
) -> tuple[list[str], list[str], str | None]:
    """Walk back over consecutive attribute_item / line_comment siblings.

    Returns (derive_macros, attributes, docstring).
    """
    derives: list[str] = []
    attributes: list[str] = []
    doc_lines: list[str] = []

    prev = node.prev_sibling
    while prev is not None:
        if prev.type == "attribute_item":
            attr = _parse_attribute(prev, source)
            if attr is None:
                prev = prev.prev_sibling
                continue
            name, args_text = attr
            if name == "derive" and args_text:
                inner = args_text.strip("()").strip()
                derives = [d.strip() for d in inner.split(",") if d.strip()] + derives
            else:
                attributes.insert(0, _node_text(prev, source).strip())
        elif prev.type == "line_comment":
            text = _node_text(prev, source)
            if text.startswith("///") or text.startswith("//!"):
                doc_lines.insert(0, text)
            else:
                break
        elif prev.type == "block_comment":
            text = _node_text(prev, source)
            if text.startswith("/**") or text.startswith("/*!"):
                doc_lines.insert(0, text)
            break
        else:
            break
        prev = prev.prev_sibling

    docstring = "\n".join(doc_lines) if doc_lines else None
    return derives, attributes, docstring


def _parse_attribute(attr_item: Node, source: bytes) -> tuple[str, str] | None:
    """Return (attribute_name, args_text) or None."""
    for child in attr_item.children:
        if child.type == "attribute":
            name_node = next(
                (
                    c
                    for c in child.children
                    if c.type in ("identifier", "scoped_identifier")
                ),
                None,
            )
            if name_node is None:
                return None
            name = _node_text(name_node, source).split("::")[-1]
            args = next((c for c in child.children if c.type == "token_tree"), None)
            return name, _node_text(args, source) if args else ""
    return None


def _http_route_from_attributes(attributes: list[str]) -> tuple[str | None, str | None]:
    """Detect Axum/Actix/Rocket-style HTTP route attributes."""
    for raw in attributes:
        text = raw.strip("# []")
        match = re.match(r"([a-zA-Z_][a-zA-Z0-9_:]*)\s*\((.*)\)\s*$", text, re.DOTALL)
        if not match:
            continue
        name = match.group(1).split("::")[-1]
        if name.lower() not in _HTTP_ATTRIBUTE_NAMES:
            continue
        args = match.group(2)
        path_match = re.search(r'"([^"]+)"', args)
        return name.upper(), path_match.group(1) if path_match else None
    return None, None


def _function_modifiers(node: Node, source: bytes) -> dict[str, bool]:
    flags = {"is_async": False, "is_unsafe": False, "is_const": False}
    for child in node.children:
        if child.type == "function_modifiers":
            text = _node_text(child, source)
            flags["is_async"] = "async" in text
            flags["is_unsafe"] = "unsafe" in text
            flags["is_const"] = "const" in text
    return flags


def _signature(node: Node, source: bytes) -> str:
    body = node.child_by_field_name("body")
    if body:
        return (
            source[node.start_byte : body.start_byte]
            .decode("utf-8", errors="replace")
            .strip()
        )
    text = _node_text(node, source).split("{", 1)[0]
    return text.split(";", 1)[0].strip()


def _impl_target(node: Node, source: bytes) -> str:
    """For `impl Foo` / `impl Trait for Foo`, return the implementing type."""
    type_node = node.child_by_field_name("type")
    if type_node is None:
        for child in node.children:
            if child.type in (
                "type_identifier",
                "generic_type",
                "scoped_type_identifier",
            ):
                type_node = child
                break
    if type_node is None:
        return "impl"
    return _node_text(type_node, source).split("<")[0].strip()


def _parse_function(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    parent_name: str | None = None,
) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    name = _node_text(name_node, source)

    derives, attributes, docstring = _collect_preceding(node, source)
    http_method, http_route = _http_route_from_attributes(attributes)
    flags = _function_modifiers(node, source)

    sym_type = "function" if parent_name is None else "method"

    extras: dict[str, Any] = {
        **flags,
        "derive_macros": derives,
        "http_method": http_method,
        "http_route": http_route,
    }

    return CodeSymbol(
        name=name,
        symbol_type=sym_type,
        language="rust",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        package=package,
        annotations=attributes,
        signature=_signature(node, source),
        docstring=docstring,
        extras=extras,
    )


def _parse_typed_item(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    sym_type: str,
    parent_name: str | None = None,
) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    derives, attributes, docstring = _collect_preceding(node, source)
    return CodeSymbol(
        name=_node_text(name_node, source),
        symbol_type=sym_type,
        language="rust",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        package=package,
        annotations=attributes,
        signature=_signature(node, source),
        docstring=docstring,
        extras={"derive_macros": derives},
    )


_TYPE_NODE_TO_SYMBOL: dict[str, str] = {
    "struct_item": "struct",
    "enum_item": "enum",
    "trait_item": "trait",
    "type_item": "type",
    "union_item": "union",
}


def _walk_items(
    container: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    parent_name: str | None,
    symbols: list[CodeSymbol],
) -> None:
    for child in container.children:
        if child.type in ("function_item", "function_signature_item"):
            sym = _parse_function(child, source, file_path, package, parent_name)
            if sym:
                symbols.append(sym)
        elif child.type in _TYPE_NODE_TO_SYMBOL:
            sym = _parse_typed_item(
                child,
                source,
                file_path,
                package,
                _TYPE_NODE_TO_SYMBOL[child.type],
                parent_name,
            )
            if sym:
                symbols.append(sym)
        elif child.type == "impl_item":
            target = _impl_target(child, source)
            body = child.child_by_field_name("body") or next(
                (c for c in child.children if c.type == "declaration_list"), None
            )
            if body is not None:
                _walk_items(body, source, file_path, package, target, symbols)
        elif child.type == "mod_item":
            name_node = child.child_by_field_name("name")
            if name_node is None:
                continue
            mod_name = _node_text(name_node, source)
            sub_pkg = f"{package}::{mod_name}" if package else mod_name
            sym = _parse_typed_item(
                child, source, file_path, package, "module", parent_name
            )
            if sym:
                symbols.append(sym)
            body = next(
                (c for c in child.children if c.type == "declaration_list"), None
            )
            if body is not None:
                _walk_items(body, source, file_path, sub_pkg, parent_name, symbols)


class RustParser:
    def __init__(self) -> None:
        self._parser = Parser(RUST_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".rs"]

    def language(self) -> str:
        return "rust"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        symbols: list[CodeSymbol] = []
        _walk_items(tree.root_node, source, file_path, None, None, symbols)
        return symbols
