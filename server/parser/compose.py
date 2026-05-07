from __future__ import annotations

import yaml
import tree_sitter_yaml
from tree_sitter import Language, Node, Parser

from server.parser.base import CodeSymbol, _node_text

YAML_LANGUAGE = Language(tree_sitter_yaml.language())


def _scalar_text(node: Node, source: bytes) -> str:
    if node.type in ("double_quote_scalar", "single_quote_scalar"):
        raw = _node_text(node, source)
        return raw[1:-1] if len(raw) >= 2 else raw
    for child in node.children:
        if child.type in (
            "plain_scalar",
            "string_scalar",
            "double_quote_scalar",
            "single_quote_scalar",
        ):
            return _scalar_text(child, source)
    return _node_text(node, source).strip()


def _find_service_lines(source: bytes) -> dict[str, int]:
    """Return {service_name: 1-indexed line} using the tree-sitter AST."""
    tree = Parser(YAML_LANGUAGE).parse(source)
    result: dict[str, int] = {}

    def find_services_mapping(node: Node) -> Node | None:
        if node.type == "block_mapping_pair":
            key = node.child_by_field_name("key")
            val = node.child_by_field_name("value")
            if key and _scalar_text(key, source) == "services" and val:
                for child in val.children:
                    if child.type == "block_mapping":
                        return child
        for child in node.children:
            found = find_services_mapping(child)
            if found is not None:
                return found
        return None

    services_bm = find_services_mapping(tree.root_node)
    if services_bm:
        for child in services_bm.children:
            if child.type == "block_mapping_pair":
                key = child.child_by_field_name("key")
                if key:
                    result[_scalar_text(key, source)] = key.start_point[0] + 1

    return result


def _to_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, dict):
        return [f"{k}={v}" for k, v in value.items()]
    return []


class ComposeParser:
    def supported_extensions(self) -> list[str]:
        return []

    def language(self) -> str:
        return "docker-compose"

    def supported_filenames(self) -> list[str]:
        return [
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ]

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        text = source.decode("utf-8", errors="replace")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            return []

        if not isinstance(data, dict):
            return []

        services: dict = data.get("services") or {}
        if not services:
            return []

        service_lines = _find_service_lines(source)
        symbols: list[CodeSymbol] = []

        for svc_name, svc_cfg in services.items():
            if not isinstance(svc_cfg, dict):
                svc_cfg = {}

            image: str | None = svc_cfg.get("image")
            build = svc_cfg.get("build")
            ports = _to_str_list(svc_cfg.get("ports") or [])
            volumes = _to_str_list(svc_cfg.get("volumes") or [])
            environment = _to_str_list(svc_cfg.get("environment") or [])
            depends_on_raw = svc_cfg.get("depends_on") or []
            depends_on = (
                list(depends_on_raw.keys())
                if isinstance(depends_on_raw, dict)
                else list(depends_on_raw)
            )

            svc_source = yaml.dump(
                {svc_name: svc_cfg}, default_flow_style=False, allow_unicode=True
            ).rstrip()

            if image:
                signature = f"service {svc_name}: image={image}"
            elif build:
                ctx = (
                    build.get("context", ".") if isinstance(build, dict) else str(build)
                )
                signature = f"service {svc_name}: build context={ctx}"
            else:
                signature = f"service {svc_name}"

            start_line = service_lines.get(svc_name, 1)

            symbols.append(
                CodeSymbol(
                    name=svc_name,
                    symbol_type="service",
                    language="docker-compose",
                    source=svc_source,
                    file_path=file_path,
                    start_line=start_line,
                    end_line=start_line,
                    parent_name=None,
                    package=None,
                    annotations=[],
                    signature=signature,
                    docstring=None,
                    extras={
                        "image": image,
                        "build": (
                            build.get("context")
                            if isinstance(build, dict)
                            else str(build)
                        )
                        if build
                        else None,
                        "ports": ports,
                        "volumes": volumes,
                        "environment": environment,
                        "depends_on": depends_on,
                    },
                )
            )

        return symbols
