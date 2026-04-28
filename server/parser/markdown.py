from __future__ import annotations

import re

from server.parser.base import CodeSymbol

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")


class MarkdownParser:
    def supported_extensions(self) -> list[str]:
        return [".md"]

    def language(self) -> str:
        return "markdown"

    def supported_filenames(self) -> list[str]:
        return []

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        text = source.decode("utf-8", errors="replace")
        lines = text.splitlines()
        symbols: list[CodeSymbol] = []

        # ── Locate all ATX headings (# through ######) ────────────────────────
        # Each entry: (line_no_1indexed, level, heading_text, raw_heading_line)
        headings: list[tuple[int, int, str, str]] = []
        for i, line in enumerate(lines):
            m = _HEADING_RE.match(line)
            if m:
                level = len(m.group(1))
                heading_text = m.group(2).strip()
                headings.append((i + 1, level, heading_text, line))

        # ── Build section symbols ─────────────────────────────────────────────
        for idx, (line_no, level, heading_text, raw_heading) in enumerate(headings):
            # Section content runs from this heading up to (but not including) the next
            next_start = headings[idx + 1][0] - 1 if idx + 1 < len(headings) else len(lines)
            section_lines = lines[line_no - 1:next_start]
            section_source = "\n".join(section_lines)
            end_line = line_no - 1 + len(section_lines)

            # Determine parent: nearest preceding heading with a lower level number
            parent_name: str | None = None
            for prev_line_no, prev_level, prev_text, _ in reversed(headings[:idx]):
                if prev_level < level:
                    parent_name = prev_text
                    break

            symbols.append(CodeSymbol(
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
            ))

        # ── If there's content before the first heading, emit a document symbol
        if headings and headings[0][0] > 1:
            intro = "\n".join(lines[: headings[0][0] - 1]).strip()
            if intro:
                doc_name = file_path.rsplit("/", 1)[-1]
                symbols.insert(0, CodeSymbol(
                    name=doc_name,
                    symbol_type="document",
                    language="markdown",
                    source=intro,
                    file_path=file_path,
                    start_line=1,
                    end_line=headings[0][0] - 1,
                    parent_name=None,
                    package=None,
                    annotations=[],
                    signature=doc_name,
                    extras={"level": 0},
                ))

        # ── Fallback: no headings → single document symbol for the whole file ──
        if not headings:
            doc_name = file_path.rsplit("/", 1)[-1]
            symbols.append(CodeSymbol(
                name=doc_name,
                symbol_type="document",
                language="markdown",
                source=text,
                file_path=file_path,
                start_line=1,
                end_line=len(lines) or 1,
                parent_name=None,
                package=None,
                annotations=[],
                signature=doc_name,
                extras={"level": 0},
            ))

        return symbols
