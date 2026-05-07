from __future__ import annotations

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from server.parser.base import CodeSymbol, _node_text


def _docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    lines: list[str] = []
    while prev is not None:
        if prev.type == "comment":
            text = _node_text(prev, source)
            if text.startswith("#'") or text.startswith("#"):
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
    text = _node_text(node, source)
    return text.split("\n", 1)[0].strip()


def _is_assignment(op_node: Node, source: bytes) -> bool:
    for child in op_node.children:
        if child.type in ("<-", "=", "<<-"):
            return True
    return False


def _parse_assignment(node: Node, source: bytes, file_path: str) -> CodeSymbol | None:
    """An R function declaration is `name <- function(...)`."""
    if not _is_assignment(node, source):
        return None
    children = node.children
    if len(children) < 3:
        return None
    lhs = children[0]
    rhs = children[-1]
    if rhs.type != "function_definition":
        return None
    if lhs.type not in ("identifier",):
        return None
    name = _node_text(lhs, source)
    return CodeSymbol(
        name=name,
        symbol_type="function",
        language="r",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=_signature(node, source),
        docstring=_docstring(node, source),
    )


def _parse_s4_call(node: Node, source: bytes, file_path: str) -> CodeSymbol | None:
    """Detect setClass / setGeneric / setMethod calls."""
    fn = next((c for c in node.children if c.type == "identifier"), None)
    if fn is None:
        return None
    fn_name = _node_text(fn, source)
    s4_map = {"setClass": "class", "setGeneric": "generic", "setMethod": "method"}
    if fn_name not in s4_map:
        return None

    args = next((c for c in node.children if c.type == "arguments"), None)
    if args is None:
        return None
    name: str | None = None
    for child in args.children:
        if child.type == "argument":
            for sub in child.children:
                if sub.type == "string":
                    text = _node_text(sub, source).strip()
                    name = text.strip("'\"")
                    break
            if name:
                break
    if name is None:
        return None

    return CodeSymbol(
        name=name,
        symbol_type=s4_map[fn_name],
        language="r",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=_signature(node, source),
        docstring=_docstring(node, source),
    )


_r_parser = None


def _get_r_parser():
    global _r_parser
    if _r_parser is None:
        _r_parser = get_parser("r")
    return _r_parser


class RParser:
    def __init__(self) -> None:
        self._parser = _get_r_parser()

    def supported_extensions(self) -> list[str]:
        return [".r", ".R"]

    def language(self) -> str:
        return "r"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        symbols: list[CodeSymbol] = []
        for child in tree.root_node.children:
            if child.type == "binary_operator":
                sym = _parse_assignment(child, source, file_path)
                if sym:
                    symbols.append(sym)
            elif child.type == "call":
                sym = _parse_s4_call(child, source, file_path)
                if sym:
                    symbols.append(sym)
        return symbols
