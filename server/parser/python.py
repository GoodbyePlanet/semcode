from __future__ import annotations

import os

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol

PYTHON_LANGUAGE = Language(tree_sitter_python.language())

_PYDANTIC_BASES = {"BaseModel", "BaseSettings"}


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _file_to_module(file_path: str) -> str:
    parts = file_path.replace(os.sep, "/")
    if parts.endswith(".py"):
        parts = parts[:-3]
    return parts.replace("/", ".")


def _get_docstring(body_node: Node, source: bytes) -> str | None:
    if body_node is None:
        return None
    for child in body_node.children:
        if child.type == "expression_statement":
            for sub in child.children:
                if sub.type == "string":
                    return _node_text(sub, source)
        elif child.type not in ("\n", "comment"):
            break
    return None


def _get_decorators(node: Node, source: bytes) -> list[str]:
    decorators = []
    sibling = node.prev_sibling
    # decorated_definition wraps the node along with decorators
    # but we also handle when node is inside decorated_definition
    if node.parent and node.parent.type == "decorated_definition":
        for child in node.parent.children:
            if child.type == "decorator":
                decorators.append(_node_text(child, source).lstrip("@").strip())
    return decorators


def _get_fastapi_route(decorators: list[str]) -> tuple[str | None, str | None]:
    for dec in decorators:
        for method in ("get", "post", "put", "delete", "patch"):
            if f".{method}(" in dec or dec.startswith(f"{method}("):
                route = None
                # Extract path string from decorator like router.get("/api/chat")
                import re
                m = re.search(r'["\']([^"\']+)["\']', dec)
                if m:
                    route = m.group(1)
                return method.upper(), route
    return None, None


def _classify_class(name: str, bases: list[str], decorators: list[str]) -> str:
    for base in bases:
        if base in _PYDANTIC_BASES or "BaseModel" in base or "BaseSettings" in base:
            return "pydantic_model"
    for dec in decorators:
        if "dataclass" in dec:
            return "dataclass"
    return "class"


def _classify_function(name: str, decorators: list[str], is_async: bool) -> str:
    for dec in decorators:
        for method in ("get", "post", "put", "delete", "patch"):
            if f".{method}(" in dec or dec.startswith(f"{method}("):
                return "api_route"
        if "asynccontextmanager" in dec or "contextmanager" in dec:
            return "lifecycle_hook"
    return "function"


def _parse_class(
    node: Node,
    source: bytes,
    file_path: str,
    module: str,
    parent_name: str | None = None,
) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []

    name_node = node.child_by_field_name("name")
    if name_node is None:
        return []

    class_name = _node_text(name_node, source)
    decorators = _get_decorators(node, source)

    bases = []
    args = node.child_by_field_name("superclasses")
    if args:
        for child in args.children:
            if child.type not in (",", "(", ")"):
                bases.append(_node_text(child, source))

    sym_type = _classify_class(class_name, bases, decorators)
    body = node.child_by_field_name("body")
    docstring = _get_docstring(body, source)

    signature = f"class {class_name}"
    if bases:
        signature += f"({', '.join(bases)})"

    symbols.append(CodeSymbol(
        name=class_name,
        symbol_type=sym_type,
        language="python",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        package=module,
        annotations=decorators,
        signature=signature,
        docstring=docstring,
        extras={"bases": bases},
    ))

    # Parse methods
    if body:
        for child in body.children:
            actual = child
            if child.type == "decorated_definition":
                for sub in child.children:
                    if sub.type == "function_definition":
                        actual = sub
                        break
            if actual.type == "function_definition":
                fn = _parse_function(actual, source, file_path, module, class_name)
                if fn:
                    symbols.append(fn)

    return symbols


def _parse_function(
    node: Node,
    source: bytes,
    file_path: str,
    module: str,
    parent_name: str | None = None,
) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None

    fn_name = _node_text(name_node, source)
    decorators = _get_decorators(node, source)
    src = _node_text(node, source)
    is_async = src.lstrip().startswith("async ")

    http_method, http_route = _get_fastapi_route(decorators)
    sym_type = _classify_function(fn_name, decorators, is_async)

    params = node.child_by_field_name("parameters")
    return_type = node.child_by_field_name("return_type")

    sig_parts = []
    if is_async:
        sig_parts.append("async")
    sig_parts.append("def")
    sig_parts.append(fn_name)
    if params:
        sig_parts.append(_node_text(params, source))
    if return_type:
        sig_parts.append("->")
        sig_parts.append(_node_text(return_type, source).lstrip(":").strip())

    signature = " ".join(sig_parts)

    body = node.child_by_field_name("body")
    docstring = _get_docstring(body, source)

    return CodeSymbol(
        name=fn_name,
        symbol_type=sym_type,
        language="python",
        source=src,
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        package=module,
        annotations=decorators,
        signature=signature,
        docstring=docstring,
        extras={
            "is_async": is_async,
            "http_method": http_method,
            "http_route": http_route,
        },
    )


class PythonParser:
    def __init__(self) -> None:
        self._parser = Parser(PYTHON_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".py"]

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        root = tree.root_node
        module = _file_to_module(file_path)
        symbols: list[CodeSymbol] = []

        for child in root.children:
            actual = child
            if child.type == "decorated_definition":
                for sub in child.children:
                    if sub.type in ("class_definition", "function_definition"):
                        actual = sub
                        break

            if actual.type == "class_definition":
                symbols.extend(_parse_class(actual, source, file_path, module))
            elif actual.type == "function_definition":
                fn = _parse_function(actual, source, file_path, module)
                if fn:
                    symbols.append(fn)

        return symbols
