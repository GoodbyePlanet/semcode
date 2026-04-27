from __future__ import annotations

from html.parser import HTMLParser

from server.parser.base import CodeSymbol

_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_STRUCTURAL_TAGS = frozenset({
    "section", "article", "nav", "header", "footer",
    "main", "aside", "form", "template", "dialog",
})


class _Extractor(HTMLParser):
    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self._lines = lines
        self.entries: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_dict = {k.lower(): v for k, v in attrs}
        elem_id = attr_dict.get("id")

        if tag not in _HEADING_TAGS and tag not in _STRUCTURAL_TAGS and not elem_id:
            return

        line_no = self.getpos()[0]
        name = elem_id or f"<{tag}> line {line_no}"
        raw_line = self._lines[line_no - 1].strip() if line_no <= len(self._lines) else name

        extras: dict = {"tag": tag}
        if elem_id:
            extras["id"] = elem_id
        if attr_dict.get("class"):
            extras["class"] = attr_dict["class"]

        self.entries.append({
            "tag": tag,
            "name": name,
            "line_no": line_no,
            "raw_line": raw_line,
            "extras": extras,
        })


class HtmlParser:
    def supported_extensions(self) -> list[str]:
        return [".html", ".htm"]

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        text = source.decode("utf-8", errors="replace")
        lines = text.splitlines()
        filename = file_path.rsplit("/", 1)[-1]

        extractor = _Extractor(lines)
        try:
            extractor.feed(text)
        except Exception:
            pass

        symbols: list[CodeSymbol] = []
        for entry in extractor.entries:
            tag = entry["tag"]
            symbol_type = "heading" if tag in _HEADING_TAGS else "element"
            raw = entry["raw_line"]
            symbols.append(CodeSymbol(
                name=entry["name"],
                symbol_type=symbol_type,
                language="html",
                source=raw,
                file_path=file_path,
                start_line=entry["line_no"],
                end_line=entry["line_no"],
                parent_name=None,
                package=None,
                annotations=[],
                signature=raw,
                docstring=None,
                extras=entry["extras"],
            ))

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
