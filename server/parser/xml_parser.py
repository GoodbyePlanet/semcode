from __future__ import annotations

import tree_sitter_xml
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

XML_LANGUAGE = Language(tree_sitter_xml.language_xml())


def _elem_name(elem_node: Node, source: bytes) -> str:
    for tag_node in elem_node.children:
        if tag_node.type in ("STag", "EmptyElemTag"):
            name_node = next((c for c in tag_node.children if c.type == "Name"), None)
            return _node_text(name_node, source).strip() if name_node else ""
    return ""


def _strip_ns(name: str) -> str:
    return name.split(":")[-1] if ":" in name else name


def _elem_attrs(elem_node: Node, source: bytes) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for tag_node in elem_node.children:
        if tag_node.type in ("STag", "EmptyElemTag"):
            for attr in tag_node.children:
                if attr.type == "Attribute":
                    names = [c for c in attr.children if c.type == "Name"]
                    vals = [c for c in attr.children if c.type == "AttValue"]
                    if names:
                        key = _strip_ns(_node_text(names[0], source))
                        val = _node_text(vals[0], source).strip('"\'') if vals else ""
                        attrs[key] = val
    return attrs


def _elem_text(elem_node: Node | None, source: bytes) -> str:
    if elem_node is None:
        return ""
    for child in elem_node.children:
        if child.type == "content":
            for sub in child.children:
                if sub.type == "CharData":
                    return _node_text(sub, source).strip()
    return ""


def _find_children(elem_node: Node, source: bytes, local_tag: str) -> list[Node]:
    result: list[Node] = []
    for child in elem_node.children:
        if child.type == "content":
            for sub in child.children:
                if sub.type == "element":
                    if _strip_ns(_elem_name(sub, source)) == local_tag:
                        result.append(sub)
    return result


def _child_text(elem_node: Node, source: bytes, tag: str) -> str:
    children = _find_children(elem_node, source, tag)
    return _elem_text(children[0] if children else None, source)


def _make_doc(filename: str, text: str, file_path: str, total_lines: int) -> CodeSymbol:
    return CodeSymbol(
        name=filename,
        symbol_type="document",
        language="xml",
        source=text,
        file_path=file_path,
        start_line=1,
        end_line=total_lines,
        signature=filename,
    )


def _parse_pom(
    root: Node,
    source: bytes,
    text: str,
    file_path: str,
    filename: str,
    total_lines: int,
) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []

    group_id = _child_text(root, source, "groupId")
    artifact_id = _child_text(root, source, "artifactId")
    version = _child_text(root, source, "version")
    proj_name = f"{group_id}:{artifact_id}" if group_id and artifact_id else filename
    sig = f"{proj_name}:{version}" if version else proj_name

    symbols.append(CodeSymbol(
        name=proj_name,
        symbol_type="project",
        language="xml",
        source=text,
        file_path=file_path,
        start_line=1,
        end_line=total_lines,
        signature=sig,
        extras={"groupId": group_id, "artifactId": artifact_id, "version": version},
    ))

    # Dependencies (direct + managed)
    dep_containers: list[tuple[Node, bool]] = []
    for dep_node in _find_children(root, source, "dependencies"):
        dep_containers.append((dep_node, False))
    for dm in _find_children(root, source, "dependencyManagement"):
        for deps in _find_children(dm, source, "dependencies"):
            dep_containers.append((deps, True))

    for container, managed in dep_containers:
        for dep in _find_children(container, source, "dependency"):
            g = _child_text(dep, source, "groupId")
            a = _child_text(dep, source, "artifactId")
            v = _child_text(dep, source, "version")
            scope = _child_text(dep, source, "scope")
            dep_name = f"{g}:{a}" if g and a else a or g or "dependency"
            dep_sig = dep_name + (f":{v}" if v else "") + (f" [{scope}]" if scope else "")
            symbols.append(CodeSymbol(
                name=dep_name,
                symbol_type="dependency",
                language="xml",
                source=_node_text(dep, source),
                file_path=file_path,
                start_line=dep.start_point[0] + 1,
                end_line=dep.end_point[0] + 1,
                signature=dep_sig,
                extras={"groupId": g, "artifactId": a, "version": v, "scope": scope, "managed": managed},
            ))

    # Plugins
    for build_node in _find_children(root, source, "build"):
        plugin_containers = _find_children(build_node, source, "plugins")
        for pm in _find_children(build_node, source, "pluginManagement"):
            plugin_containers += _find_children(pm, source, "plugins")
        for plugins_node in plugin_containers:
            for plugin in _find_children(plugins_node, source, "plugin"):
                g = _child_text(plugin, source, "groupId")
                a = _child_text(plugin, source, "artifactId")
                v = _child_text(plugin, source, "version")
                plugin_name = f"{g}:{a}" if g and a else a or g or "plugin"
                plugin_sig = f"{plugin_name}:{v}" if v else plugin_name
                symbols.append(CodeSymbol(
                    name=plugin_name,
                    symbol_type="plugin",
                    language="xml",
                    source=_node_text(plugin, source),
                    file_path=file_path,
                    start_line=plugin.start_point[0] + 1,
                    end_line=plugin.end_point[0] + 1,
                    signature=plugin_sig,
                    extras={"groupId": g, "artifactId": a, "version": v},
                ))

    return symbols


def _parse_spring_beans(
    root: Node,
    source: bytes,
    text: str,
    file_path: str,
    filename: str,
    total_lines: int,
) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []
    for bean in _find_children(root, source, "bean"):
        attrs = _elem_attrs(bean, source)
        bean_id = attrs.get("id", "")
        bean_class = attrs.get("class", "")
        short_class = bean_class.rsplit(".", 1)[-1] if bean_class else ""
        bean_name = bean_id or short_class or "bean"
        sig = (
            f'<bean id="{bean_id}" class="{bean_class}">'
            if bean_id
            else f'<bean class="{bean_class}">'
        )
        symbols.append(CodeSymbol(
            name=bean_name,
            symbol_type="bean",
            language="xml",
            source=_node_text(bean, source),
            file_path=file_path,
            start_line=bean.start_point[0] + 1,
            end_line=bean.end_point[0] + 1,
            signature=sig,
            extras=attrs,
        ))
    return symbols


def _parse_generic(
    root: Node,
    source: bytes,
    text: str,
    file_path: str,
    filename: str,
    total_lines: int,
) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []
    children: list[Node] = []
    for child in root.children:
        if child.type == "content":
            for sub in child.children:
                if sub.type == "element":
                    children.append(sub)

    include_all = len(children) <= 20

    for child in children:
        tag = _strip_ns(_elem_name(child, source))
        attrs = _elem_attrs(child, source)
        elem_id = attrs.get("id") or attrs.get("name")
        if not elem_id and not include_all:
            continue
        elem_name = elem_id or f"<{tag}>"
        attr_preview = " ".join(f'{k}="{v}"' for k, v in list(attrs.items())[:3])
        sig = f"<{tag}" + (f" {attr_preview}" if attr_preview else "") + ">"
        symbols.append(CodeSymbol(
            name=elem_name,
            symbol_type="element",
            language="xml",
            source=_node_text(child, source),
            file_path=file_path,
            start_line=child.start_point[0] + 1,
            end_line=child.end_point[0] + 1,
            signature=sig,
            extras={"tag": tag, **attrs},
        ))

    return symbols


class XmlParser:
    def __init__(self) -> None:
        self._parser = Parser(XML_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return [".xml"]

    def language(self) -> str:
        return "xml"

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        text = source.decode("utf-8", errors="replace")
        lines = text.splitlines()
        filename = file_path.rsplit("/", 1)[-1]
        total_lines = len(lines) or 1

        tree = self._parser.parse(source)
        root = tree.root_node

        root_elem = next((c for c in root.children if c.type == "element"), None)
        if root_elem is None:
            return [_make_doc(filename, text, file_path, total_lines)]

        root_tag = _strip_ns(_elem_name(root_elem, source))

        if filename == "pom.xml" or root_tag == "project":
            symbols = _parse_pom(root_elem, source, text, file_path, filename, total_lines)
        elif root_tag == "beans":
            symbols = _parse_spring_beans(root_elem, source, text, file_path, filename, total_lines)
        else:
            symbols = _parse_generic(root_elem, source, text, file_path, filename, total_lines)

        return symbols or [_make_doc(filename, text, file_path, total_lines)]
