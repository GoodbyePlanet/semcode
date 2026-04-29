from __future__ import annotations

import tree_sitter_dockerfile
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

DOCKERFILE_LANGUAGE = Language(tree_sitter_dockerfile.language())

_INDEXED_INSTRUCTIONS = frozenset({
    "run_instruction", "copy_instruction", "env_instruction",
    "expose_instruction", "entrypoint_instruction", "cmd_instruction",
})


def _image_spec_text(from_node: Node, source: bytes) -> str:
    spec = next((c for c in from_node.children if c.type == "image_spec"), None)
    return _node_text(spec, source).strip() if spec else ""


def _image_alias_text(from_node: Node, source: bytes) -> str | None:
    alias_node = from_node.child_by_field_name("as")
    if alias_node is None:
        alias_node = next((c for c in from_node.children if c.type == "image_alias"), None)
    return _node_text(alias_node, source).strip() if alias_node else None


def _env_pairs(env_node: Node, source: bytes) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for child in env_node.children:
        if child.type == "env_pair":
            name_node = child.child_by_field_name("name")
            val_node = child.child_by_field_name("value")
            if name_node:
                pairs.append((
                    _node_text(name_node, source).strip(),
                    _node_text(val_node, source).strip() if val_node else "",
                ))
    return pairs


def _expose_ports(expose_node: Node, source: bytes) -> list[str]:
    return [
        _node_text(c, source).strip()
        for c in expose_node.children
        if c.type == "expose_port"
    ]


def _copy_name(copy_node: Node, source: bytes) -> str:
    paths = [_node_text(c, source).strip() for c in copy_node.children if c.type == "path"]
    if len(paths) >= 2:
        return f"{paths[-2]} → {paths[-1]}"
    return _node_text(copy_node, source).strip()


def _run_command(run_node: Node, source: bytes) -> str:
    for child in run_node.children:
        if child.type in ("shell_command", "exec_form"):
            return _node_text(child, source).strip()
    return _node_text(run_node, source).strip()


class DockerfileParser:
    def __init__(self) -> None:
        self._parser = Parser(DOCKERFILE_LANGUAGE)

    def supported_extensions(self) -> list[str]:
        return []

    def language(self) -> str:
        return "dockerfile"

    def supported_filenames(self) -> list[str]:
        return ["Dockerfile", "dockerfile"]

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        tree = self._parser.parse(source)
        root = tree.root_node

        # Group instructions into stages at each from_instruction
        stages: list[tuple[str, str | None, list[Node]]] = []  # (base_image, alias, nodes)
        cur_base: str | None = None
        cur_alias: str | None = None
        cur_nodes: list[Node] = []

        for child in root.children:
            if child.type == "from_instruction":
                if cur_base is not None:
                    stages.append((cur_base, cur_alias, cur_nodes))
                cur_base = _image_spec_text(child, source)
                cur_alias = _image_alias_text(child, source)
                cur_nodes = [child]
            elif cur_base is not None and child.type != "comment":
                cur_nodes.append(child)

        if cur_base is not None:
            stages.append((cur_base, cur_alias, cur_nodes))

        symbols: list[CodeSymbol] = []

        for stage_idx, (base_image, alias, stage_nodes) in enumerate(stages):
            stage_name = alias if alias else f"stage-{stage_idx}"
            stage_start = stage_nodes[0].start_point[0] + 1
            stage_end = stage_nodes[-1].end_point[0] + 1

            exposed_ports: list[str] = []
            env_vars: list[str] = []
            entrypoint: str | None = None
            cmd: str | None = None

            for node in stage_nodes:
                if node.type == "expose_instruction":
                    exposed_ports.extend(_expose_ports(node, source))
                elif node.type == "env_instruction":
                    for k, v in _env_pairs(node, source):
                        env_vars.append(f"{k}={v}" if v else k)
                elif node.type == "entrypoint_instruction":
                    entrypoint = _node_text(node, source).strip()
                elif node.type == "cmd_instruction":
                    cmd = _node_text(node, source).strip()

            stage_source = source[
                stage_nodes[0].start_byte:stage_nodes[-1].end_byte
            ].decode("utf-8", errors="replace")

            symbols.append(CodeSymbol(
                name=stage_name,
                symbol_type="stage",
                language="dockerfile",
                source=stage_source,
                file_path=file_path,
                start_line=stage_start,
                end_line=stage_end,
                parent_name=None,
                package=None,
                annotations=[],
                signature="FROM " + base_image + (f" AS {alias}" if alias else ""),
                docstring=None,
                extras={
                    "base_image": base_image,
                    "stage_alias": alias,
                    "exposed_ports": exposed_ports,
                    "env_vars": env_vars,
                    "entrypoint": entrypoint,
                    "cmd": cmd,
                },
            ))

            for node in stage_nodes:
                if node.type not in _INDEXED_INSTRUCTIONS:
                    continue

                line_no = node.start_point[0] + 1
                node_text = _node_text(node, source).strip()

                if node.type == "env_instruction":
                    for k, v in _env_pairs(node, source):
                        symbols.append(CodeSymbol(
                            name=k,
                            symbol_type="env_var",
                            language="dockerfile",
                            source=node_text,
                            file_path=file_path,
                            start_line=line_no,
                            end_line=node.end_point[0] + 1,
                            parent_name=stage_name,
                            package=None,
                            annotations=[],
                            signature=node_text,
                            extras={"instruction": "ENV", "value": v},
                        ))

                elif node.type == "expose_instruction":
                    ports = _expose_ports(node, source)
                    symbols.append(CodeSymbol(
                        name=" ".join(ports),
                        symbol_type="expose",
                        language="dockerfile",
                        source=node_text,
                        file_path=file_path,
                        start_line=line_no,
                        end_line=node.end_point[0] + 1,
                        parent_name=stage_name,
                        package=None,
                        annotations=[],
                        signature=node_text,
                        extras={"instruction": "EXPOSE", "ports": ports},
                    ))

                elif node.type == "entrypoint_instruction":
                    symbols.append(CodeSymbol(
                        name="ENTRYPOINT",
                        symbol_type="entrypoint",
                        language="dockerfile",
                        source=node_text,
                        file_path=file_path,
                        start_line=line_no,
                        end_line=node.end_point[0] + 1,
                        parent_name=stage_name,
                        package=None,
                        annotations=[],
                        signature=node_text,
                        extras={"instruction": "ENTRYPOINT", "value": node_text},
                    ))

                elif node.type == "cmd_instruction":
                    symbols.append(CodeSymbol(
                        name="CMD",
                        symbol_type="cmd",
                        language="dockerfile",
                        source=node_text,
                        file_path=file_path,
                        start_line=line_no,
                        end_line=node.end_point[0] + 1,
                        parent_name=stage_name,
                        package=None,
                        annotations=[],
                        signature=node_text,
                        extras={"instruction": "CMD", "value": node_text},
                    ))

                elif node.type == "run_instruction":
                    cmd_text = _run_command(node, source)
                    run_name = cmd_text[:60] + "..." if len(cmd_text) > 60 else cmd_text
                    symbols.append(CodeSymbol(
                        name=run_name,
                        symbol_type="run_instruction",
                        language="dockerfile",
                        source=node_text,
                        file_path=file_path,
                        start_line=line_no,
                        end_line=node.end_point[0] + 1,
                        parent_name=stage_name,
                        package=None,
                        annotations=[],
                        signature=node_text,
                        extras={"instruction": "RUN", "command": cmd_text},
                    ))

                elif node.type == "copy_instruction":
                    copy_name = _copy_name(node, source)
                    symbols.append(CodeSymbol(
                        name=copy_name,
                        symbol_type="copy_instruction",
                        language="dockerfile",
                        source=node_text,
                        file_path=file_path,
                        start_line=line_no,
                        end_line=node.end_point[0] + 1,
                        parent_name=stage_name,
                        package=None,
                        annotations=[],
                        signature=node_text,
                        extras={"instruction": "COPY", "value": node_text},
                    ))

        return symbols
