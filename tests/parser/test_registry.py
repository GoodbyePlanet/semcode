from __future__ import annotations

import pytest

from server.parser import registry
from server.parser.bash import BashParser
from server.parser.c import CParser
from server.parser.compose import ComposeParser
from server.parser.cpp import CppParser
from server.parser.csharp import CSharpParser
from server.parser.css_parser import CssParser
from server.parser.dart import DartParser
from server.parser.dockerfile import DockerfileParser
from server.parser.go import GoParser
from server.parser.html_parser import HtmlParser
from server.parser.java import JavaParser
from server.parser.json_parser import JsonParser
from server.parser.kotlin import KotlinParser
from server.parser.lua import LuaParser
from server.parser.markdown import MarkdownParser
from server.parser.php import PhpParser
from server.parser.python import PythonParser
from server.parser.r import RParser
from server.parser.ruby import RubyParser
from server.parser.rust import RustParser
from server.parser.scala import ScalaParser
from server.parser.sql import SqlParser
from server.parser.swift import SwiftParser
from server.parser.typescript import TypeScriptParser


@pytest.mark.parametrize(
    "path, expected_cls",
    [
        ("svc/foo.go", GoParser),
        ("svc/Foo.java", JavaParser),
        ("svc/foo.py", PythonParser),
        ("svc/Foo.ts", TypeScriptParser),
        ("svc/Foo.tsx", TypeScriptParser),
        ("svc/foo.js", TypeScriptParser),
        ("svc/foo.jsx", TypeScriptParser),
        ("svc/README.md", MarkdownParser),
        ("svc/package.json", JsonParser),
        ("svc/page.html", HtmlParser),
        ("svc/page.htm", HtmlParser),
        ("svc/styles.css", CssParser),
        ("svc/lib.rs", RustParser),
        ("svc/Foo.cs", CSharpParser),
        ("svc/main.c", CParser),
        ("svc/header.h", CParser),
        ("svc/widget.cpp", CppParser),
        ("svc/widget.cc", CppParser),
        ("svc/widget.cxx", CppParser),
        ("svc/widget.hpp", CppParser),
        ("svc/widget.hh", CppParser),
        ("svc/users.rb", RubyParser),
        ("svc/UserController.php", PhpParser),
        ("svc/UserController.kt", KotlinParser),
        ("svc/build.kts", KotlinParser),
        ("svc/UserController.scala", ScalaParser),
        ("svc/script.sc", ScalaParser),
        ("svc/UserView.swift", SwiftParser),
        ("svc/main.dart", DartParser),
        ("svc/deploy.sh", BashParser),
        ("svc/run.bash", BashParser),
        ("svc/schema.sql", SqlParser),
        ("svc/utils.lua", LuaParser),
        ("svc/utils.r", RParser),
        ("svc/utils.R", RParser),
    ],
)
def test_extension_routing(path, expected_cls):
    parser = registry.get_parser(path)
    assert isinstance(parser, expected_cls)


@pytest.mark.parametrize(
    "path, expected_cls",
    [
        ("svc/Dockerfile", DockerfileParser),
        ("svc/dockerfile", DockerfileParser),
        ("svc/docker-compose.yml", ComposeParser),
        ("svc/docker-compose.yaml", ComposeParser),
        ("svc/compose.yml", ComposeParser),
        ("svc/compose.yaml", ComposeParser),
    ],
)
def test_filename_routing(path, expected_cls):
    parser = registry.get_parser(path)
    assert isinstance(parser, expected_cls)


def test_unknown_extension_returns_none():
    assert registry.get_parser("svc/data.bin") is None
    assert registry.get_parser("svc/no_extension") is None


def test_parse_file_returns_empty_for_unknown_extension():
    assert registry.parse_file(b"whatever", "svc/data.bin") == []


def test_parse_file_swallows_parser_exceptions(monkeypatch):
    class BoomParser:
        def parse_file(self, source, file_path):
            raise RuntimeError("boom")

        def supported_extensions(self):
            return [".boom"]

    monkeypatch.setattr(registry, "_PARSERS", {".boom": BoomParser()})
    monkeypatch.setattr(registry, "_FILENAME_PARSERS", {})

    assert registry.parse_file(b"x", "svc/file.boom") == []


def test_parse_file_dispatches_to_correct_parser(read_fixture):
    src = read_fixture("go/router.go")
    syms = registry.parse_file(src, "svc/router.go")
    assert syms
    assert all(s.language == "go" for s in syms)
