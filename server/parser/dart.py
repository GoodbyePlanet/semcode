from __future__ import annotations

from typing import Any

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from server.parser.base import CodeSymbol, _node_text

_FLUTTER_WIDGET_BASES = {
    "StatelessWidget",
    "StatefulWidget",
    "State",
    "InheritedWidget",
}


def _docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    while prev is not None:
        if prev.type == "documentation_comment":
            return _node_text(prev, source)
        if prev.type in ("\n", " ", "comment"):
            prev = prev.prev_sibling
            continue
        break
    return None


def _signature(node: Node, source: bytes) -> str:
    text = _node_text(node, source)
    return text.split("{", 1)[0].split("=>", 1)[0].split(";", 1)[0].strip()


def _superclass(node: Node, source: bytes) -> str | None:
    for child in node.children:
        if child.type == "superclass":
            for sub in child.children:
                if sub.type == "type_identifier":
                    return _node_text(sub, source)
    return None


def _name_from_identifier_or_field(node: Node, source: bytes) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node:
        return _node_text(name_node, source)
    for child in node.children:
        if child.type == "identifier":
            return _node_text(child, source)
        if child.type == "type_identifier":
            return _node_text(child, source)
    return None


def _collect_annotations_in_body_for_node(target: Node, source: bytes) -> list[str]:
    """In Dart, annotations are siblings preceding a method_signature/declaration."""
    out: list[str] = []
    prev = target.prev_sibling
    while prev is not None:
        if prev.type == "annotation":
            for sub in prev.children:
                if sub.type == "identifier":
                    out.insert(0, _node_text(sub, source))
                    break
            prev = prev.prev_sibling
            continue
        if prev.type in ("\n", " ", "comment", "documentation_comment"):
            prev = prev.prev_sibling
            continue
        break
    return out


def _parse_function_signature(
    fn_sig_node: Node,
    surrounding_node: Node,
    source: bytes,
    file_path: str,
    parent_name: str | None,
) -> CodeSymbol | None:
    name = _name_from_identifier_or_field(fn_sig_node, source)
    if name is None:
        return None
    annotations = _collect_annotations_in_body_for_node(surrounding_node, source)
    sym_type = "method" if parent_name else "function"

    return CodeSymbol(
        name=name,
        symbol_type=sym_type,
        language="dart",
        source=_node_text(surrounding_node, source),
        file_path=file_path,
        start_line=surrounding_node.start_point[0] + 1,
        end_line=surrounding_node.end_point[0] + 1,
        parent_name=parent_name,
        annotations=annotations,
        signature=_signature(fn_sig_node, source),
        docstring=_docstring(surrounding_node, source),
    )


def _parse_constructor_signature(
    ctor_node: Node,
    source: bytes,
    file_path: str,
    parent_name: str,
) -> CodeSymbol | None:
    name = _name_from_identifier_or_field(ctor_node, source)
    if name is None:
        return None
    return CodeSymbol(
        name=name,
        symbol_type="constructor",
        language="dart",
        source=_node_text(ctor_node, source),
        file_path=file_path,
        start_line=ctor_node.start_point[0] + 1,
        end_line=ctor_node.end_point[0] + 1,
        parent_name=parent_name,
        signature=_signature(ctor_node, source),
        docstring=_docstring(ctor_node, source),
    )


def _walk_class_body(
    body: Node,
    source: bytes,
    file_path: str,
    parent_name: str,
    symbols: list[CodeSymbol],
) -> None:
    for child in body.children:
        if child.type == "method_signature":
            for sub in child.children:
                if sub.type == "function_signature":
                    sym = _parse_function_signature(
                        sub, child, source, file_path, parent_name
                    )
                    if sym:
                        symbols.append(sym)
                    break
                if sub.type == "constructor_signature":
                    sym = _parse_constructor_signature(
                        sub, source, file_path, parent_name
                    )
                    if sym:
                        symbols.append(sym)
                    break
        elif child.type == "declaration":
            for sub in child.children:
                if sub.type == "function_signature":
                    sym = _parse_function_signature(
                        sub, child, source, file_path, parent_name
                    )
                    if sym:
                        symbols.append(sym)
                    break
                if sub.type == "constructor_signature":
                    sym = _parse_constructor_signature(
                        sub, source, file_path, parent_name
                    )
                    if sym:
                        symbols.append(sym)
                    break


def _parse_class_like(
    node: Node,
    source: bytes,
    file_path: str,
) -> list[CodeSymbol]:
    name = _name_from_identifier_or_field(node, source)
    if name is None:
        return []

    superclass = _superclass(node, source)
    is_widget = superclass in _FLUTTER_WIDGET_BASES if superclass else False
    annotations = [
        _node_text(c.children[1], source)
        for c in node.children
        if c.type == "annotation"
        and len(c.children) > 1
        and c.children[1].type == "identifier"
    ]

    if node.type == "mixin_declaration":
        sym_type = "mixin"
    elif node.type == "extension_declaration":
        sym_type = "extension"
    elif node.type == "enum_declaration":
        sym_type = "enum"
    elif is_widget:
        sym_type = "widget"
    else:
        sym_type = "class"

    extras: dict[str, Any] = {
        "superclass": superclass,
        "is_flutter_widget": is_widget,
    }

    symbols: list[CodeSymbol] = [
        CodeSymbol(
            name=name,
            symbol_type=sym_type,
            language="dart",
            source=_node_text(node, source),
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
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
            if c.type in ("class_body", "extension_body", "enum_body")
        ),
        None,
    )
    if body is not None:
        _walk_class_body(body, source, file_path, name, symbols)

    return symbols


def _walk(
    container: Node,
    source: bytes,
    file_path: str,
    symbols: list[CodeSymbol],
) -> None:
    children = list(container.children)
    i = 0
    while i < len(children):
        child = children[i]
        if child.type in (
            "class_definition",
            "mixin_declaration",
            "extension_declaration",
            "enum_declaration",
        ):
            symbols.extend(_parse_class_like(child, source, file_path))
        elif child.type == "function_signature":
            sym = _parse_function_signature(child, child, source, file_path, None)
            if sym:
                # Use surrounding range that includes the body if present.
                if i + 1 < len(children) and children[i + 1].type == "function_body":
                    body = children[i + 1]
                    sym.end_line = body.end_point[0] + 1
                    sym.source = source[child.start_byte : body.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                symbols.append(sym)
        i += 1


_dart_parser = None


def _get_dart_parser():
    global _dart_parser
    if _dart_parser is None:
        _dart_parser = get_parser("dart")
    return _dart_parser


class DartParser:
    def __init__(self) -> None:
        self._parser = _get_dart_parser()

    def supported_extensions(self) -> list[str]:
        return [".dart"]

    def language(self) -> str:
        return "dart"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        symbols: list[CodeSymbol] = []
        _walk(tree.root_node, source, file_path, symbols)
        return symbols
