from __future__ import annotations

import tree_sitter_html
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

HTML_LANGUAGE = Language(tree_sitter_html.language())

_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_STRUCTURAL_TAGS = frozenset({
    "section", "article", "nav", "header", "footer",
    "main", "aside", "form", "template", "dialog",
})


def _tag_name(node: Node, source: bytes) -> str:
    name_node = next((c for c in node.children if c.type == "tag_name"), None)
    return _node_text(name_node, source).lower() if name_node else ""


def _tag_attributes(node: Node, source: bytes) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for child in node.children:
        if child.type == "attribute":
            name_node = next((c for c in child.children if c.type == "attribute_name"), None)
            if not name_node:
                continue
            val = ""
            quoted = next((c for c in child.children if c.type == "quoted_attribute_value"), None)
            if quoted:
                inner = next((c for c in quoted.children if c.type == "attribute_value"), None)
                val = _node_text(inner, source) if inner else ""
            else:
                unquoted = next((c for c in child.children if c.type == "attribute_value"), None)
                if unquoted:
                    val = _node_text(unquoted, source)
            attrs[_node_text(name_node, source).lower()] = val
    return attrs


def _collect_symbols(
    node: Node,
    source: bytes,
    lines: list[str],
    file_path: str,
    symbols: list[CodeSymbol],
) -> None:
    if node.type in ("start_tag", "self_closing_tag"):
        tag = _tag_name(node, source)
        attrs = _tag_attributes(node, source)
        elem_id = attrs.get("id")

        if tag in _HEADING_TAGS or tag in _STRUCTURAL_TAGS or elem_id:
            line_no = node.start_point[0] + 1
            name = elem_id or f"<{tag}> line {line_no}"
            raw_line = lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else name
            symbol_type = "heading" if tag in _HEADING_TAGS else "element"

            extras: dict = {"tag": tag}
            if elem_id:
                extras["id"] = elem_id
            if attrs.get("class"):
                extras["class"] = attrs["class"]

            symbols.append(CodeSymbol(
                name=name,
                symbol_type=symbol_type,
                language="html",
                source=raw_line,
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                parent_name=None,
                package=None,
                annotations=[],
                signature=raw_line,
                docstring=None,
                extras=extras,
            ))

    for child in node.children:
        _collect_symbols(child, source, lines, file_path, symbols)


class HtmlParser:
    def __init__(self) -> None:
        self._parser = Parser(HTML_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".html", ".htm"]

    def language(self) -> str:
        return "html"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        text = source.decode("utf-8", errors="replace")
        lines = text.splitlines()
        filename = file_path.rsplit("/", 1)[-1]
        tree = self._parser.parse(source)

        symbols: list[CodeSymbol] = []
        _collect_symbols(tree.root_node, source, lines, file_path, symbols)

        if not symbols:
            symbols.append(CodeSymbol(
                name=filename,
                symbol_type="document",
                language="html",
                source=text,
                file_path=file_path,
                start_line=1,
                end_line=len(lines) or 1,
                parent_name=None,
                package=None,
                annotations=[],
                signature=filename,
                docstring=None,
                extras={},
            ))

        return symbols
