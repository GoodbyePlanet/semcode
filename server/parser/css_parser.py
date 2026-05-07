from __future__ import annotations

import tree_sitter_css
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

CSS_LANGUAGE = Language(tree_sitter_css.language())


def _extract_declarations(block_node: Node, source: bytes) -> list[str]:
    props: list[str] = []
    for child in block_node.children:
        if child.type == "declaration":
            prop_node = next(
                (c for c in child.children if c.type == "property_name"), None
            )
            if prop_node:
                props.append(_node_text(prop_node, source).strip())
    return props


class CssParser:
    def __init__(self) -> None:
        self._parser = Parser(CSS_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".css"]

    def language(self) -> str:
        return "css"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        text = source.decode("utf-8", errors="replace")
        lines = text.splitlines()
        filename = file_path.rsplit("/", 1)[-1]
        tree = self._parser.parse(source)
        root = tree.root_node

        symbols: list[CodeSymbol] = []

        for node in root.children:
            if node.type == "rule_set":
                sel_node = next(
                    (c for c in node.children if c.type == "selectors"), None
                )
                block_node = next((c for c in node.children if c.type == "block"), None)
                if not sel_node:
                    continue

                sel = _node_text(sel_node, source).strip()
                if not sel:
                    continue

                props = _extract_declarations(block_node, source) if block_node else []
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                name = sel if len(sel) <= 100 else sel[:97] + "..."
                raw_source = "\n".join(lines[start_line - 1 : end_line])
                sig = lines[start_line - 1].strip() if start_line <= len(lines) else sel

                symbols.append(
                    CodeSymbol(
                        name=name,
                        symbol_type="rule",
                        language="css",
                        source=raw_source,
                        file_path=file_path,
                        start_line=start_line,
                        end_line=end_line,
                        parent_name=None,
                        package=None,
                        annotations=[],
                        signature=sig,
                        docstring=None,
                        extras={"properties": props},
                    )
                )

        if not symbols:
            symbols.append(
                CodeSymbol(
                    name=filename,
                    symbol_type="document",
                    language="css",
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
                )
            )

        return symbols
