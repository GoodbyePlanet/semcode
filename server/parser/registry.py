from __future__ import annotations

from server.parser.base import CodeSymbol, LanguageParser
from server.parser.compose import ComposeParser
from server.parser.dockerfile import DockerfileParser
from server.parser.go import GoParser
from server.parser.java import JavaParser
from server.parser.json_parser import JsonParser
from server.parser.markdown import MarkdownParser
from server.parser.python import PythonParser
from server.parser.typescript import TypeScriptParser

# extension (e.g. ".go") → parser
_PARSERS: dict[str, LanguageParser] = {}
# exact basename (e.g. "Dockerfile", "docker-compose.yml") → parser
_FILENAME_PARSERS: dict[str, LanguageParser] = {}


def _build_registry() -> tuple[dict[str, LanguageParser], dict[str, LanguageParser]]:
    ext_registry: dict[str, LanguageParser] = {}
    name_registry: dict[str, LanguageParser] = {}
    all_parsers: list[LanguageParser] = [
        GoParser(),
        JavaParser(),
        PythonParser(),
        TypeScriptParser(),
        DockerfileParser(),
        ComposeParser(),
        MarkdownParser(),
        JsonParser(),
    ]
    for parser in all_parsers:
        for ext in parser.supported_extensions():
            ext_registry[ext] = parser
        # supported_filenames() is an optional extension of the protocol
        if hasattr(parser, "supported_filenames"):
            for fname in parser.supported_filenames():  # type: ignore[union-attr]
                name_registry[fname] = parser
    return ext_registry, name_registry


def get_parser(file_path: str) -> LanguageParser | None:
    global _PARSERS, _FILENAME_PARSERS
    if not _PARSERS:
        _PARSERS, _FILENAME_PARSERS = _build_registry()

    # Exact filename match takes priority (handles Dockerfile, docker-compose.yml, …)
    basename = file_path.rsplit("/", 1)[-1]
    if basename in _FILENAME_PARSERS:
        return _FILENAME_PARSERS[basename]

    # Fall back to extension-based match
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
