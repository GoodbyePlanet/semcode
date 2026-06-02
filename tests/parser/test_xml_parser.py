from __future__ import annotations

from server.parser.xml_parser import XmlParser


def test_invalid_xml_returns_document_fallback() -> None:
    syms = XmlParser().parse_file(b"<not valid xml", "svc/broken.xml")
    assert len(syms) == 1
    assert syms[0].symbol_type == "document"
    assert syms[0].name == "broken.xml"


def test_empty_file_returns_document_fallback() -> None:
    syms = XmlParser().parse_file(b"", "svc/empty.xml")
    assert len(syms) == 1
    assert syms[0].symbol_type == "document"


def test_pom_fixture(read_fixture) -> None:
    src = read_fixture("xml/pom.xml")
    syms = XmlParser().parse_file(src, "svc/pom.xml")

    types = [s.symbol_type for s in syms]
    assert "project" in types
    assert types.count("dependency") == 3
    assert types.count("plugin") == 1

    project = next(s for s in syms if s.symbol_type == "project")
    assert project.name == "com.example:demo-app"
    assert project.extras["version"] == "1.0.0"
    assert "com.example:demo-app:1.0.0" in project.signature

    deps = [s for s in syms if s.symbol_type == "dependency"]
    dep_names = [d.name for d in deps]
    assert "org.springframework.boot:spring-boot-starter-web" in dep_names
    assert "org.springframework.boot:spring-boot-starter-security" in dep_names

    test_dep = next(d for d in deps if "starter-test" in d.name)
    assert "test" in test_dep.signature

    plugin = next(s for s in syms if s.symbol_type == "plugin")
    assert plugin.name == "org.springframework.boot:spring-boot-maven-plugin"
    assert "3.2.0" in plugin.signature


def test_spring_beans_fixture(read_fixture) -> None:
    src = read_fixture("xml/beans.xml")
    syms = XmlParser().parse_file(src, "svc/beans.xml")

    types = [s.symbol_type for s in syms]
    assert types.count("bean") == 3

    bean_names = [s.name for s in syms]
    assert "userService" in bean_names
    assert "userRepository" in bean_names

    # Bean with only class (no id) uses short class name
    assert "SecurityConfig" in bean_names


def test_generic_xml_extracts_elements() -> None:
    src = b"""<?xml version="1.0"?>
<config>
    <server id="main" host="localhost" port="8080"/>
    <server id="backup" host="backup.example.com" port="8080"/>
    <timeout value="30"/>
</config>"""
    syms = XmlParser().parse_file(src, "svc/config.xml")
    names = [s.name for s in syms]
    assert "main" in names
    assert "backup" in names


def test_language_is_xml() -> None:
    syms = XmlParser().parse_file(b"<root/>", "svc/test.xml")
    assert all(s.language == "xml" for s in syms)


def test_file_path_preserved() -> None:
    syms = XmlParser().parse_file(b"<root/>", "my-service/config/settings.xml")
    assert all(s.file_path == "my-service/config/settings.xml" for s in syms)
