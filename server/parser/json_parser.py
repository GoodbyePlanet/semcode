from __future__ import annotations

import tree_sitter_json
from tree_sitter import Language, Parser

from server.parser.base import CodeSymbol, _node_text

JSON_LANGUAGE = Language(tree_sitter_json.language())


class JsonParser:
    def __init__(self) -> None:
        self._parser = Parser(JSON_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".json"]

    def language(self) -> str:
        return "json"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        text = source.decode("utf-8", errors="replace")
        lines = text.splitlines()
        filename = file_path.rsplit("/", 1)[-1]
        tree = self._parser.parse(source)
        root = tree.root_node

        top_keys: list[str] = []

        obj_node = next((c for c in root.children if c.type == "object"), None)
        if obj_node:
            for child in obj_node.children:
                if child.type == "pair":
                    key_node = child.child_by_field_name("key")
                    if key_node:
                        # Extract string_content to avoid surrounding quotes
                        content_node = next(
                            (c for c in key_node.children if c.type == "string_content"),
                            None,
                        )
                        if content_node:
                            top_keys.append(_node_text(content_node, source))

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
