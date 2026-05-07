from __future__ import annotations

from typing import Any

import tree_sitter_php
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

PHP_LANGUAGE = Language(tree_sitter_php.language_php())

_HTTP_METHOD_ATTRS: dict[str, str] = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Delete": "DELETE",
    "Patch": "PATCH",
}

_LARAVEL_BASES = {
    "Controller": "controller",
    "BaseController": "controller",
    "Model": "model",
    "Eloquent\\Model": "model",
}


def _docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    while prev is not None:
        if prev.type == "comment":
            text = _node_text(prev, source)
            if text.startswith("/**"):
                return text
            break
        if prev.type in ("\n", " "):
            prev = prev.prev_sibling
            continue
        break
    return None


def _attribute_name(attr_node: Node, source: bytes) -> str | None:
    name_node = attr_node.child_by_field_name("name")
    if name_node is None:
        for child in attr_node.children:
            if child.type in ("name", "qualified_name"):
                name_node = child
                break
    if name_node:
        return _node_text(name_node, source).split("\\")[-1]
    return None


def _argument_string(arg_node: Node, source: bytes) -> str | None:
    """Pull the string content out of a `string` AST node."""
    for child in arg_node.children:
        if child.type == "string_content":
            return _node_text(child, source)
    text = _node_text(arg_node, source).strip()
    if (text.startswith("'") and text.endswith("'")) or (
        text.startswith('"') and text.endswith('"')
    ):
        return text[1:-1]
    return None


def _attribute_args_node(attr_node: Node) -> Node | None:
    args = attr_node.child_by_field_name("arguments")
    if args is not None:
        return args
    for child in attr_node.children:
        if child.type == "arguments":
            return child
    return None


def _attribute_first_string(attr_node: Node, source: bytes) -> str | None:
    args = _attribute_args_node(attr_node)
    if args is None:
        return None
    for child in args.children:
        if child.type == "argument":
            for sub in child.children:
                if sub.type == "string":
                    return _argument_string(sub, source)
        elif child.type == "string":
            return _argument_string(child, source)
    return None


def _route_methods_from_attribute(attr_node: Node, source: bytes) -> list[str]:
    args = _attribute_args_node(attr_node)
    if args is None:
        return []
    methods: list[str] = []
    for child in args.children:
        if child.type != "argument":
            continue
        # named argument: methods: [...]
        name = next((c for c in child.children if c.type == "name"), None)
        if name is None or _node_text(name, source) != "methods":
            continue
        for sub in child.children:
            if sub.type == "array_creation_expression":
                for el in sub.children:
                    if el.type == "array_element_initializer":
                        s = next((c for c in el.children if c.type == "string"), None)
                        if s:
                            text = _argument_string(s, source)
                            if text:
                                methods.append(text.upper())
    return methods


def _collect_attributes(node: Node, source: bytes) -> list[Node]:
    attrs: list[Node] = []
    for child in node.children:
        if child.type == "attribute_list":
            for group in child.children:
                if group.type == "attribute_group":
                    for sub in group.children:
                        if sub.type == "attribute":
                            attrs.append(sub)
    return attrs


def _http_route(
    attrs: list[Node], source: bytes, base_route: str | None = None
) -> tuple[str | None, str | None]:
    for attr in attrs:
        name = _attribute_name(attr, source)
        if name is None:
            continue
        if name == "Route":
            path = _attribute_first_string(attr, source) or ""
            methods = _route_methods_from_attribute(attr, source)
            method = methods[0] if methods else "REQUEST"
            route = (base_route or "") + path
            return method, route or None
        if name in _HTTP_METHOD_ATTRS:
            path = _attribute_first_string(attr, source) or ""
            return _HTTP_METHOD_ATTRS[name], (base_route or "") + path or None
    return None, None


def _signature(node: Node, source: bytes) -> str:
    body = node.child_by_field_name("body")
    if body:
        return (
            source[node.start_byte : body.start_byte]
            .decode("utf-8", errors="replace")
            .strip()
        )
    return _node_text(node, source).split("{", 1)[0].split(";", 1)[0].strip()


def _superclass(node: Node, source: bytes) -> str | None:
    for child in node.children:
        if child.type == "base_clause":
            for sub in child.children:
                if sub.type in ("name", "qualified_name"):
                    return _node_text(sub, source)
    return None


def _parse_method(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    parent_name: str,
    base_route: str | None,
    stereotype: str | None,
) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None

    attrs = _collect_attributes(node, source)
    annotations = [n for attr in attrs if (n := _attribute_name(attr, source))]
    http_method, http_route = _http_route(attrs, source, base_route)

    return CodeSymbol(
        name=_node_text(name_node, source),
        symbol_type="method",
        language="php",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        package=package,
        annotations=annotations,
        signature=_signature(node, source),
        docstring=_docstring(node, source),
        extras={
            "stereotype": stereotype,
            "http_method": http_method,
            "http_route": http_route,
        },
    )


_TYPE_DECL_TO_SYMBOL = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "trait_declaration": "trait",
    "enum_declaration": "enum",
}


def _parse_type_decl(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
) -> list[CodeSymbol]:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return []
    name = _node_text(name_node, source)

    attrs = _collect_attributes(node, source)
    annotations = [n for attr in attrs if (n := _attribute_name(attr, source))]
    superclass = _superclass(node, source) if node.type == "class_declaration" else None
    stereotype = _LARAVEL_BASES.get(superclass) if superclass else None

    base_route: str | None = None
    for attr in attrs:
        if _attribute_name(attr, source) == "Route":
            base_route = _attribute_first_string(attr, source)
            break

    sym_type = stereotype or _TYPE_DECL_TO_SYMBOL.get(node.type, "class")

    extras: dict[str, Any] = {
        "stereotype": stereotype,
        "superclass": superclass,
        "base_route": base_route,
    }

    symbols: list[CodeSymbol] = [
        CodeSymbol(
            name=name,
            symbol_type=sym_type,
            language="php",
            source=_node_text(node, source),
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            package=package,
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
            if c.type in ("declaration_list", "enum_declaration_list")
        ),
        None,
    )
    if body is None:
        return symbols
    for child in body.children:
        if child.type == "method_declaration":
            m = _parse_method(
                child, source, file_path, package, name, base_route, stereotype
            )
            if m:
                symbols.append(m)

    return symbols


def _parse_function(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return CodeSymbol(
        name=_node_text(name_node, source),
        symbol_type="function",
        language="php",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        package=package,
        signature=_signature(node, source),
        docstring=_docstring(node, source),
    )


def _walk(
    container: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    symbols: list[CodeSymbol],
) -> None:
    for child in container.children:
        if child.type == "namespace_definition":
            name_node = child.child_by_field_name("name")
            sub_pkg = (
                _node_text(name_node, source).replace("\\", ".")
                if name_node
                else package
            )
            body = next(
                (c for c in child.children if c.type == "compound_statement"), None
            )
            if body is not None:
                _walk(body, source, file_path, sub_pkg, symbols)
            else:
                # File-scoped namespace: rest of file belongs to it. Update outer package state.
                # The grammar emits remaining declarations as siblings — we handle below in caller.
                package = sub_pkg
        elif child.type in _TYPE_DECL_TO_SYMBOL:
            symbols.extend(_parse_type_decl(child, source, file_path, package))
        elif child.type == "function_definition":
            sym = _parse_function(child, source, file_path, package)
            if sym:
                symbols.append(sym)


def _file_scoped_package(root: Node, source: bytes) -> str | None:
    for child in root.children:
        if child.type == "namespace_definition":
            name_node = child.child_by_field_name("name")
            if name_node and not any(
                c.type == "compound_statement" for c in child.children
            ):
                return _node_text(name_node, source).replace("\\", ".")
    return None


class PhpParser:
    def __init__(self) -> None:
        self._parser = Parser(PHP_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".php"]

    def language(self) -> str:
        return "php"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        root = tree.root_node
        package = _file_scoped_package(root, source)
        symbols: list[CodeSymbol] = []
        _walk(root, source, file_path, package, symbols)
        return symbols
