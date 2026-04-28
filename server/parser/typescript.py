from __future__ import annotations

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol

TS_LANGUAGE = Language(tree_sitter_typescript.language_typescript())
TSX_LANGUAGE = Language(tree_sitter_typescript.language_tsx())


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _has_jsx_return(node: Node, source: bytes) -> bool:
    src = _node_text(node, source)
    return (
        "<" in src
        and ("return (" in src or "return<" in src or "return (" in src)
        or "jsx" in src.lower()[:200]
    )


def _is_component_name(name: str) -> bool:
    return name and name[0].isupper()


def _is_hook_name(name: str) -> bool:
    return name.startswith("use") and len(name) > 3 and name[3].isupper()


def _get_jsdoc(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    while prev and prev.type in ("", "\n", " ", "comment"):
        if prev.type == "comment":
            text = _node_text(prev, source)
            if text.startswith("/**"):
                return text
        prev = prev.prev_sibling
    return None


def _classify_ts_function(name: str, node: Node, source: bytes) -> str:
    if _is_hook_name(name):
        return "react_hook"
    if _is_component_name(name) and _has_jsx_return(node, source):
        return "react_component"
    return "function"


def _parse_interface(node: Node, source: bytes, file_path: str) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    name = _node_text(name_node, source)
    docstring = _get_jsdoc(node, source)
    return CodeSymbol(
        name=name,
        symbol_type="interface",
        language="typescript",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=f"interface {name}",
        docstring=docstring,
        extras={},
    )


def _parse_type_alias(node: Node, source: bytes, file_path: str) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    name = _node_text(name_node, source)
    return CodeSymbol(
        name=name,
        symbol_type="type",
        language="typescript",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=f"type {name}",
        extras={},
    )


def _parse_function_node(
    node: Node,
    source: bytes,
    file_path: str,
    name: str | None = None,
) -> CodeSymbol | None:
    if name is None:
        name_node = node.child_by_field_name("name")
        if name_node:
            name = _node_text(name_node, source)
    if not name:
        return None

    sym_type = _classify_ts_function(name, node, source)
    params = node.child_by_field_name("parameters")
    return_type = node.child_by_field_name("return_type")

    sig = f"function {name}"
    if params:
        sig += _node_text(params, source)
    if return_type:
        sig += ": " + _node_text(return_type, source).lstrip(":").strip()

    docstring = _get_jsdoc(node, source)

    return CodeSymbol(
        name=name,
        symbol_type=sym_type,
        language="typescript",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=sig,
        docstring=docstring,
        extras={},
    )


def _parse_arrow_function(
    declarator_node: Node,
    source: bytes,
    file_path: str,
) -> CodeSymbol | None:
    name_node = declarator_node.child_by_field_name("name")
    if name_node is None:
        return None
    name = _node_text(name_node, source)

    value = declarator_node.child_by_field_name("value")
    if value is None:
        return None

    # Detect memo() wrapping
    uses_memo = False
    actual_fn = value
    if value.type == "call_expression":
        fn_node = value.child_by_field_name("function")
        fn_name_text = _node_text(fn_node, source) if fn_node else ""
        if fn_name_text in ("memo", "React.memo", "forwardRef", "React.forwardRef"):
            uses_memo = True
            args = value.child_by_field_name("arguments")
            if args:
                for child in args.children:
                    if child.type in ("arrow_function", "function_expression", "function"):
                        actual_fn = child
                        break

    sym_type = _classify_ts_function(name, actual_fn, source)

    docstring = _get_jsdoc(declarator_node.parent or declarator_node, source)

    return CodeSymbol(
        name=name,
        symbol_type=sym_type,
        language="typescript",
        source=_node_text(declarator_node.parent or declarator_node, source),
        file_path=file_path,
        start_line=declarator_node.start_point[0] + 1,
        end_line=declarator_node.end_point[0] + 1,
        signature=f"const {name} = ...",
        docstring=docstring,
        extras={"uses_memo": uses_memo},
    )


def _walk_and_extract(
    node: Node,
    source: bytes,
    file_path: str,
    symbols: list[CodeSymbol],
) -> None:
    target = node
    # Unwrap export statement
    if node.type == "export_statement":
        for child in node.children:
            if child.type not in ("export", "default", ";"):
                target = child
                break

    if target.type == "function_declaration":
        sym = _parse_function_node(target, source, file_path)
        if sym:
            symbols.append(sym)
        return

    if target.type == "interface_declaration":
        sym = _parse_interface(target, source, file_path)
        if sym:
            symbols.append(sym)
        return

    if target.type == "type_alias_declaration":
        sym = _parse_type_alias(target, source, file_path)
        if sym:
            symbols.append(sym)
        return

    if target.type in ("lexical_declaration", "variable_declaration"):
        for child in target.children:
            if child.type == "variable_declarator":
                value = child.child_by_field_name("value")
                if value and value.type in ("arrow_function", "call_expression"):
                    sym = _parse_arrow_function(child, source, file_path)
                    if sym:
                        symbols.append(sym)
        return

    if target.type == "class_declaration":
        name_node = target.child_by_field_name("name")
        if name_node:
            name = _node_text(name_node, source)
            symbols.append(CodeSymbol(
                name=name,
                symbol_type="class",
                language="typescript",
                source=_node_text(target, source),
                file_path=file_path,
                start_line=target.start_point[0] + 1,
                end_line=target.end_point[0] + 1,
                signature=f"class {name}",
                extras={},
            ))
        return


class TypeScriptParser:
    def __init__(self) -> None:
        self._ts = Parser(TS_LANGUAGE)
        self._tsx = Parser(TSX_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".ts", ".tsx", ".js", ".jsx"]

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        is_tsx = file_path.endswith((".tsx", ".jsx"))
        parser = self._tsx if is_tsx else self._ts
        tree = parser.parse(source)
        root = tree.root_node
        symbols: list[CodeSymbol] = []

        for child in root.children:
            _walk_and_extract(child, source, file_path, symbols)

        if not symbols and source.strip():
            basename = file_path.rsplit("/", 1)[-1]
            name = basename.rsplit(".", 1)[0] if "." in basename else basename
            total_lines = source.count(b"\n") + 1
            symbols.append(CodeSymbol(
                name=name,
                symbol_type="module",
                language="typescript",
                source=source.decode("utf-8", errors="replace"),
                file_path=file_path,
                start_line=1,
                end_line=total_lines,
                signature=basename,
                extras={"is_module": True},
            ))

        return symbols
