from __future__ import annotations

from typing import Any

import tree_sitter_ruby
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

RUBY_LANGUAGE = Language(tree_sitter_ruby.language())

_RAILS_BASES: dict[str, str] = {
    "ApplicationController": "controller",
    "ActionController::Base": "controller",
    "ActionController::API": "controller",
    "ApplicationRecord": "model",
    "ActiveRecord::Base": "model",
    "ApplicationJob": "job",
    "ActiveJob::Base": "job",
    "ApplicationMailer": "mailer",
    "ActionMailer::Base": "mailer",
}

_DSL_NAMES = {
    "has_many",
    "has_one",
    "belongs_to",
    "validates",
    "validate",
    "before_action",
    "after_action",
    "around_action",
    "before_save",
    "after_save",
    "scope",
    "attr_accessor",
    "attr_reader",
    "attr_writer",
}


def _docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_sibling
    lines: list[str] = []
    while prev is not None and prev.type == "comment":
        text = _node_text(prev, source)
        lines.insert(0, text)
        prev = prev.prev_sibling
    return "\n".join(lines) if lines else None


def _superclass_name(node: Node, source: bytes) -> str | None:
    superclass = node.child_by_field_name("superclass")
    if superclass is None:
        return None
    for child in superclass.children:
        if child.type in ("constant", "scope_resolution"):
            return _node_text(child, source)
    return None


def _signature(node: Node, source: bytes) -> str:
    text = _node_text(node, source).split("\n", 1)[0]
    return text.strip()


def _collect_dsl_calls(body: Node | None, source: bytes) -> list[str]:
    if body is None:
        return []
    calls: list[str] = []
    for child in body.children:
        if child.type == "call":
            for sub in child.children:
                if sub.type == "identifier":
                    name = _node_text(sub, source)
                    if name in _DSL_NAMES:
                        calls.append(name)
                    break
    return calls


def _parse_method(
    node: Node,
    source: bytes,
    file_path: str,
    parent_name: str | None,
) -> CodeSymbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    name = _node_text(name_node, source)
    sym_type = "class_method" if node.type == "singleton_method" else "method"

    return CodeSymbol(
        name=name,
        symbol_type=sym_type,
        language="ruby",
        source=_node_text(node, source),
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        signature=_signature(node, source),
        docstring=_docstring(node, source),
    )


def _parse_class_or_module(
    node: Node,
    source: bytes,
    file_path: str,
    parent_name: str | None = None,
) -> list[CodeSymbol]:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return []

    name = _node_text(name_node, source)
    superclass = _superclass_name(node, source) if node.type == "class" else None
    rails_kind = _RAILS_BASES.get(superclass) if superclass else None
    sym_type = rails_kind or ("module" if node.type == "module" else "class")

    body = node.child_by_field_name("body") or next(
        (c for c in node.children if c.type == "body_statement"), None
    )
    dsl_calls = _collect_dsl_calls(body, source)

    extras: dict[str, Any] = {
        "rails_kind": rails_kind,
        "superclass": superclass,
        "dsl_calls": dsl_calls,
    }

    symbols: list[CodeSymbol] = [
        CodeSymbol(
            name=name,
            symbol_type=sym_type,
            language="ruby",
            source=_node_text(node, source),
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            parent_name=parent_name,
            signature=f"{node.type} {name}"
            + (f" < {superclass}" if superclass else ""),
            docstring=_docstring(node, source),
            extras=extras,
        )
    ]

    if body is not None:
        for child in body.children:
            if child.type in ("method", "singleton_method"):
                m = _parse_method(child, source, file_path, name)
                if m:
                    symbols.append(m)
            elif child.type in ("class", "module"):
                symbols.extend(_parse_class_or_module(child, source, file_path, name))

    return symbols


def _walk(
    container: Node,
    source: bytes,
    file_path: str,
    symbols: list[CodeSymbol],
) -> None:
    for child in container.children:
        if child.type in ("class", "module"):
            symbols.extend(_parse_class_or_module(child, source, file_path))
        elif child.type in ("method", "singleton_method"):
            m = _parse_method(child, source, file_path, None)
            if m:
                symbols.append(m)


class RubyParser:
    def __init__(self) -> None:
        self._parser = Parser(RUBY_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".rb"]

    def language(self) -> str:
        return "ruby"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        symbols: list[CodeSymbol] = []
        _walk(tree.root_node, source, file_path, symbols)
        return symbols
