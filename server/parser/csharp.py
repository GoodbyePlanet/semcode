from __future__ import annotations

import tree_sitter_c_sharp
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

CSHARP_LANGUAGE = Language(tree_sitter_c_sharp.language())

_HTTP_ATTRIBUTES: dict[str, str | None] = {
    "HttpGet": "GET",
    "HttpPost": "POST",
    "HttpPut": "PUT",
    "HttpDelete": "DELETE",
    "HttpPatch": "PATCH",
    "HttpHead": "HEAD",
    "HttpOptions": "OPTIONS",
    "Route": None,
}

_STEREOTYPE_ATTRIBUTES = {
    "ApiController": "controller",
    "Controller": "controller",
}


def _attribute_name(attr_node: Node, source: bytes) -> str | None:
    name_node = attr_node.child_by_field_name("name")
    if name_node:
        return _node_text(name_node, source).split(".")[-1]
    for child in attr_node.children:
        if child.type in ("identifier", "qualified_name"):
            return _node_text(child, source).split(".")[-1]
    return None


def _attribute_first_string(attr_node: Node, source: bytes) -> str | None:
    for child in attr_node.children:
        if child.type == "attribute_argument_list":
            for arg in child.children:
                if arg.type == "attribute_argument":
                    for sub in arg.children:
                        if sub.type == "string_literal":
                            return _node_text(sub, source).strip('"')
    return None


def _collect_attributes(node: Node, source: bytes) -> list[tuple[str, Node]]:
    """Return (name, attribute_node) tuples from any attribute_list children."""
    out: list[tuple[str, Node]] = []
    for child in node.children:
        if child.type == "attribute_list":
            for sub in child.children:
                if sub.type == "attribute":
                    name = _attribute_name(sub, source)
                    if name:
                        out.append((name, sub))
    return out


def _collect_modifiers(node: Node, source: bytes) -> list[str]:
    return [_node_text(c, source) for c in node.children if c.type == "modifier"]


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
            break
        if prev.type in ("\n", " "):
            prev = prev.prev_sibling
            continue
        break
    return "\n".join(lines) if lines else None


def _signature(node: Node, source: bytes) -> str:
    body = node.child_by_field_name("body")
    if body:
        return (
            source[node.start_byte : body.start_byte]
            .decode("utf-8", errors="replace")
            .strip()
        )
    text = _node_text(node, source).split("{", 1)[0]
    return text.split("=>", 1)[0].split(";", 1)[0].strip()


def _get_namespace(root: Node, source: bytes) -> str | None:
    for child in root.children:
        if child.type in ("namespace_declaration", "file_scoped_namespace_declaration"):
            name_node = child.child_by_field_name("name")
            if name_node:
                return _node_text(name_node, source)
    return None


def _http_route(
    attributes: list[tuple[str, Node]],
    source: bytes,
    base_route: str | None,
) -> tuple[str | None, str | None]:
    for name, attr_node in attributes:
        if name in _HTTP_ATTRIBUTES:
            method = _HTTP_ATTRIBUTES[name]
            value = _attribute_first_string(attr_node, source) or ""
            if method is None and name == "Route":
                method = "REQUEST"
            full_route = (base_route or "") + value if value else (base_route or "")
            return method, full_route or None
    return None, None


def _base_route(attributes: list[tuple[str, Node]], source: bytes) -> str | None:
    for name, attr_node in attributes:
        if name == "Route":
            return _attribute_first_string(attr_node, source)
    return None


_TYPE_DECL_TO_SYMBOL = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "struct_declaration": "struct",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "record_struct_declaration": "record",
    "delegate_declaration": "delegate",
}


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

    attributes = _collect_attributes(node, source)
    modifiers = _collect_modifiers(node, source)
    annotations = [name for name, _ in attributes]
    http_method, http_route = _http_route(attributes, source, base_route)

    sym_type = "constructor" if node.type == "constructor_declaration" else "method"

    return CodeSymbol(
        name=_node_text(name_node, source),
        symbol_type=sym_type,
        language="csharp",
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
            "is_async": "async" in modifiers,
            "stereotype": stereotype,
            "http_method": http_method,
            "http_route": http_route,
        },
    )


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
    attributes = _collect_attributes(node, source)
    annotations = [n for n, _ in attributes]
    stereotype = next(
        (_STEREOTYPE_ATTRIBUTES[n] for n in annotations if n in _STEREOTYPE_ATTRIBUTES),
        None,
    )
    base_route = _base_route(attributes, source)

    sym_type = stereotype or _TYPE_DECL_TO_SYMBOL.get(node.type, "class")

    symbols: list[CodeSymbol] = [
        CodeSymbol(
            name=name,
            symbol_type=sym_type,
            language="csharp",
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
                "base_route": base_route,
            },
        )
    ]

    body = next((c for c in node.children if c.type == "declaration_list"), None)
    if body is None:
        return symbols

    for child in body.children:
        if child.type in ("method_declaration", "constructor_declaration"):
            sym = _parse_method(
                child, source, file_path, package, name, base_route, stereotype
            )
            if sym:
                symbols.append(sym)
        elif child.type in _TYPE_DECL_TO_SYMBOL:
            symbols.extend(
                _parse_type_decl(child, source, file_path, package, parent_name=name)
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
        if child.type in _TYPE_DECL_TO_SYMBOL:
            symbols.extend(_parse_type_decl(child, source, file_path, package))
        elif child.type in (
            "namespace_declaration",
            "file_scoped_namespace_declaration",
        ):
            name_node = child.child_by_field_name("name")
            sub_pkg = _node_text(name_node, source) if name_node else package
            body = next(
                (c for c in child.children if c.type == "declaration_list"), None
            )
            if body is not None:
                _walk(body, source, file_path, sub_pkg, symbols)
            else:
                # file-scoped namespace — siblings after this node belong to it
                pass


class CSharpParser:
    def __init__(self) -> None:
        self._parser = Parser(CSHARP_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".cs"]

    def language(self) -> str:
        return "csharp"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        root = tree.root_node
        package = _get_namespace(root, source)
        symbols: list[CodeSymbol] = []
        _walk(root, source, file_path, package, symbols)
        return symbols
