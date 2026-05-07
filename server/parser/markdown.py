from __future__ import annotations

import tree_sitter_markdown
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

MD_LANGUAGE = Language(tree_sitter_markdown.language())

_MARKER_LEVEL: dict[str, int] = {
    "atx_h1_marker": 1,
    "atx_h2_marker": 2,
    "atx_h3_marker": 3,
    "atx_h4_marker": 4,
    "atx_h5_marker": 5,
    "atx_h6_marker": 6,
}


def _heading_level(node: Node) -> int | None:
    for child in node.children:
        level = _MARKER_LEVEL.get(child.type)
        if level is not None:
            return level
    return None


def _heading_text(node: Node, source: bytes) -> str:
    for child in node.children:
        if child.type == "inline":
            return _node_text(child, source).strip()
    # Fallback: strip leading # markers from raw text
    return _node_text(node, source).lstrip("#").strip()


def _collect_headings(
    node: Node, source: bytes, out: list[tuple[int, int, str]]
) -> None:
    if node.type == "atx_heading":
        level = _heading_level(node)
        if level is not None:
            line_no = node.start_point[0] + 1
            text = _heading_text(node, source)
            out.append((line_no, level, text))
    for child in node.children:
        _collect_headings(child, source, out)


class MarkdownParser:
    def __init__(self) -> None:
        self._parser = Parser(MD_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".md"]

    def language(self) -> str:
        return "markdown"

    def supported_filenames(self) -> list[str]:
        return []

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        text = source.decode("utf-8", errors="replace")
        lines = text.splitlines()
        filename = file_path.rsplit("/", 1)[-1]
        tree = self._parser.parse(source)

        headings: list[tuple[int, int, str]] = []  # (line_1idx, level, text)
        _collect_headings(tree.root_node, source, headings)

        symbols: list[CodeSymbol] = []

        for idx, (line_no, level, heading_text) in enumerate(headings):
            next_start = (
                headings[idx + 1][0] - 1 if idx + 1 < len(headings) else len(lines)
            )
            section_lines = lines[line_no - 1 : next_start]
            section_source = "\n".join(section_lines)
            end_line = line_no - 1 + len(section_lines)
            raw_heading = (
                lines[line_no - 1] if line_no - 1 < len(lines) else heading_text
            )

            parent_name: str | None = None
            for prev_line_no, prev_level, prev_text in reversed(headings[:idx]):
                if prev_level < level:
                    parent_name = prev_text
                    break

            symbols.append(
                CodeSymbol(
                    name=heading_text,
                    symbol_type="section",
                    language="markdown",
                    source=section_source,
                    file_path=file_path,
                    start_line=line_no,
                    end_line=end_line,
                    parent_name=parent_name,
                    package=None,
                    annotations=[],
                    signature=raw_heading,
                    docstring=None,
                    extras={"level": level, "heading": heading_text},
                )
            )

        if headings and headings[0][0] > 1:
            intro = "\n".join(lines[: headings[0][0] - 1]).strip()
            if intro:
                symbols.insert(
                    0,
                    CodeSymbol(
                        name=filename,
                        symbol_type="document",
                        language="markdown",
                        source=intro,
                        file_path=file_path,
                        start_line=1,
                        end_line=headings[0][0] - 1,
                        parent_name=None,
                        package=None,
                        annotations=[],
                        signature=filename,
                        extras={"level": 0},
                    ),
                )

        if not headings:
            symbols.append(
                CodeSymbol(
                    name=filename,
                    symbol_type="document",
                    language="markdown",
                    source=text,
                    file_path=file_path,
                    start_line=1,
                    end_line=len(lines) or 1,
                    parent_name=None,
                    package=None,
                    annotations=[],
                    signature=filename,
                    extras={"level": 0},
                )
            )

        return symbols
