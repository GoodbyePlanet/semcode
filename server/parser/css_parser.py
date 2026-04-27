from __future__ import annotations

import re

from server.parser.base import CodeSymbol

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(text: str) -> str:
    return _COMMENT_RE.sub(" ", text)


def _scan_rules(text: str) -> list[tuple[str, int, int, str]]:
    """Yield (selector, start_line, end_line, block_content) for each CSS rule block."""
    results = []
    # segment_starts[depth] = absolute text position where the current selector begins
    segment_starts: list[int] = [0]
    # stack entries: (selector_text, open_brace_pos, selector_start_abs)
    stack: list[tuple[str, int, int]] = []

    for i, ch in enumerate(text):
        if ch == "{":
            d = len(segment_starts) - 1
            seg_start = segment_starts[d]
            surrounding = text[seg_start:i]
            sel = surrounding.strip()
            leading = len(surrounding) - len(surrounding.lstrip())
            sel_start_abs = seg_start + leading
            stack.append((sel, i, sel_start_abs))
            segment_starts.append(i + 1)

        elif ch == "}" and len(segment_starts) > 1:
            if not stack:
                segment_starts.pop()
                if segment_starts:
                    segment_starts[-1] = i + 1
                continue

            sel, open_pos, sel_start_abs = stack.pop()
            segment_starts.pop()
            if segment_starts:
                segment_starts[-1] = i + 1

            if sel and not sel.lstrip().startswith("@"):
                block = text[open_pos + 1:i]
                start_line = text[:sel_start_abs].count("\n") + 1
                end_line = text[:i].count("\n") + 1
                results.append((sel, start_line, end_line, block))

    return results


class CssParser:
    def supported_extensions(self) -> list[str]:
        return [".css"]

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        text = source.decode("utf-8", errors="replace")
        lines = text.splitlines()
        filename = file_path.rsplit("/", 1)[-1]

        clean = _strip_comments(text)
        rules = _scan_rules(clean)

        symbols: list[CodeSymbol] = []
        for sel, start_line, end_line, block in rules:
            props = []
            for part in block.split(";"):
                part = part.strip()
                if ":" in part:
                    prop = part.split(":")[0].strip()
                    if prop:
                        props.append(prop)

            name = sel if len(sel) <= 100 else sel[:97] + "..."
            raw_source = "\n".join(lines[start_line - 1:end_line])
            sig = lines[start_line - 1].strip() if start_line <= len(lines) else sel

            symbols.append(CodeSymbol(
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
            ))

        if not symbols:
            symbols.append(CodeSymbol(
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
            ))

        return symbols
