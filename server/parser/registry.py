from __future__ import annotations

from server.parser.base import CodeSymbol, LanguageParser
from server.parser.go import GoParser
from server.parser.java import JavaParser
from server.parser.python import PythonParser
from server.parser.typescript import TypeScriptParser

_PARSERS: dict[str, LanguageParser] = {}


def _build_registry() -> dict[str, LanguageParser]:
    registry: dict[str, LanguageParser] = {}
    for parser in [GoParser(), JavaParser(), PythonParser(), TypeScriptParser()]:
        for ext in parser.supported_extensions():
            registry[ext] = parser
    return registry


def get_parser(file_path: str) -> LanguageParser | None:
    global _PARSERS
    if not _PARSERS:
        _PARSERS = _build_registry()
    ext = "." + file_path.rsplit(".", 1)[-1] if "." in file_path else ""
    return _PARSERS.get(ext)


def parse_file(source: bytes, file_path: str) -> list[CodeSymbol]:
    parser = get_parser(file_path)
    if parser is None:
        return []
    try:
        return parser.parse_file(source, file_path)
    except Exception:
        return []
