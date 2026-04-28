from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from tree_sitter import Node


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


@dataclass
class CodeSymbol:
    name: str
    symbol_type: str  # class, interface, enum, record, method, function, component, hook, type
    language: str  # java, python, typescript, go
    source: str  # raw source text of this symbol
    file_path: str  # "{service_name}/{path_in_repo}"
    start_line: int
    end_line: int
    parent_name: str | None = None  # enclosing class/module
    package: str | None = None  # Java package or Python module path
    annotations: list[str] = field(default_factory=list)
    signature: str = ""  # declaration line (class Foo / def bar(...))
    docstring: str | None = None
    # language-specific extras stored as free-form dict
    extras: dict = field(default_factory=dict)


@runtime_checkable
class LanguageParser(Protocol):
    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]: ...
    def supported_extensions(self) -> list[str]: ...
    def language(self) -> str: ...
