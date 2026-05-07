from __future__ import annotations

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text
from server.parser.c import (
    _docstring,
    _function_name,
    _parse_function,
    _parse_named_type,
    _parse_typedef,
    _signature,
)

CPP_LANGUAGE = Language(tree_sitter_cpp.language())

_NAMED_TYPE_NODES = {
    "struct_specifier": "struct",
    "enum_specifier": "enum",
    "union_specifier": "union",
    "class_specifier": "class",
}


def _parse_class_member(
    node: Node,
    source: bytes,
    file_path: str,
    parent_name: str,
    package: str | None,
) -> CodeSymbol | None:
    """A class body member can be field_declaration, declaration (no body), or function_definition."""
    if node.type == "function_definition":
        return _parse_function(node, source, file_path, "cpp", parent_name, package)
    if node.type in ("field_declaration", "declaration"):
        declarator = node.child_by_field_name("declarator")
        if not _is_function_declarator(declarator):
            return None
        name = _function_name(declarator, source)
        if not name:
            return None
        return CodeSymbol(
            name=name,
            symbol_type="method",
            language="cpp",
            source=_node_text(node, source),
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            parent_name=parent_name,
            package=package,
            signature=_signature(node, source),
            docstring=_docstring(node, source),
        )
    return None


def _is_function_declarator(declarator: Node | None) -> bool:
    while declarator is not None:
        if declarator.type == "function_declarator":
            return True
        if declarator.type in ("identifier", "field_identifier", "destructor_name"):
            return False
        inner = declarator.child_by_field_name("declarator")
        if inner is None:
            return False
        declarator = inner
    return False


def _parse_class(
    node: Node,
    source: bytes,
    file_path: str,
    package: str | None,
) -> list[CodeSymbol]:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return []
    class_name = _node_text(name_node, source)

    sym_type = _NAMED_TYPE_NODES.get(node.type, "class")

    symbols: list[CodeSymbol] = [
        CodeSymbol(
            name=class_name,
            symbol_type=sym_type,
            language="cpp",
            source=_node_text(node, source),
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            package=package,
            signature=_node_text(node, source).split("{", 1)[0].strip(),
            docstring=_docstring(node, source),
        )
    ]

    body = next((c for c in node.children if c.type == "field_declaration_list"), None)
    if body is None:
        return symbols
    for child in body.children:
        sym = _parse_class_member(child, source, file_path, class_name, package)
        if sym:
            symbols.append(sym)

    return symbols


def _walk_cpp(
    container: Node,
    source: bytes,
    file_path: str,
    package: str | None,
    symbols: list[CodeSymbol],
) -> None:
    for child in container.children:
        if child.type == "function_definition":
            sym = _parse_function(child, source, file_path, "cpp", package=package)
            if sym:
                symbols.append(sym)
        elif child.type in _NAMED_TYPE_NODES:
            if child.type == "class_specifier" or (
                child.type == "struct_specifier"
                and any(c.type == "field_declaration_list" for c in child.children)
                and any(
                    sub.type
                    in ("function_definition", "field_declaration", "declaration")
                    for c in child.children
                    if c.type == "field_declaration_list"
                    for sub in c.children
                )
            ):
                symbols.extend(_parse_class(child, source, file_path, package))
            else:
                sym = _parse_named_type(child, source, file_path, "cpp")
                if sym:
                    symbols.append(sym)
        elif child.type == "type_definition":
            sym = _parse_typedef(child, source, file_path, "cpp")
            if sym:
                symbols.append(sym)
        elif child.type == "namespace_definition":
            name_node = child.child_by_field_name("name")
            ns_name = _node_text(name_node, source) if name_node else None
            sub_pkg = (
                f"{package}::{ns_name}" if package and ns_name else (ns_name or package)
            )
            body = child.child_by_field_name("body") or next(
                (c for c in child.children if c.type == "declaration_list"), None
            )
            if body is not None:
                _walk_cpp(body, source, file_path, sub_pkg, symbols)
        elif child.type == "template_declaration":
            for sub in child.children:
                if sub.type in _NAMED_TYPE_NODES:
                    cls_syms = _parse_class(sub, source, file_path, package)
                    for s in cls_syms:
                        s.extras["is_template"] = True
                    symbols.extend(cls_syms)
                elif sub.type == "function_definition":
                    fn = _parse_function(sub, source, file_path, "cpp", package=package)
                    if fn:
                        fn.extras["is_template"] = True
                        symbols.append(fn)


class CppParser:
    def __init__(self) -> None:
        self._parser = Parser(CPP_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".h++", ".c++"]

    def language(self) -> str:
        return "cpp"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        symbols: list[CodeSymbol] = []
        _walk_cpp(tree.root_node, source, file_path, None, symbols)
        return symbols
