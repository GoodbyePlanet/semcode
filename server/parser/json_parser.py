from __future__ import annotations

import json

from server.parser.base import CodeSymbol


class JsonParser:
    def supported_extensions(self) -> list[str]:
        return [".json"]

    def language(self) -> str:
        return "json"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        text = source.decode("utf-8", errors="replace")
        lines = text.splitlines()
        filename = file_path.rsplit("/", 1)[-1]

        top_keys: list[str] = []
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                top_keys = list(data.keys())
        except (json.JSONDecodeError, ValueError):
            pass

        signature = filename
        if top_keys:
            preview = ", ".join(top_keys[:10])
            if len(top_keys) > 10:
                preview += f", … ({len(top_keys)} keys)"
            signature = f"{filename} {{{preview}}}"

        return [CodeSymbol(
            name=filename,
            symbol_type="document",
            language="json",
            source=text,
            file_path=file_path,
            start_line=1,
            end_line=len(lines) or 1,
            parent_name=None,
            package=None,
            annotations=[],
            signature=signature,
            docstring=None,
            extras={"top_keys": top_keys},
        )]
