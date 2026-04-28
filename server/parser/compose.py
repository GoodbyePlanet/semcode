from __future__ import annotations

import re

import yaml

from server.parser.base import CodeSymbol


def _find_service_line(text_lines: list[str], service_name: str) -> int:
    """Return 1-indexed line where 'service_name:' first appears under 'services:'."""
    in_services = False
    # Match a line like "service_name:" (indented under services block)
    pattern = re.compile(r"^\s+" + re.escape(service_name) + r"\s*:")
    for i, line in enumerate(text_lines):
        if line.strip() == "services:":
            in_services = True
            continue
        if in_services:
            if pattern.match(line):
                return i + 1
            # Stop when we leave the services block (non-indented key)
            if line and not line[0].isspace() and line.strip().endswith(":"):
                in_services = False
    return 1  # fallback


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

        text_lines = text.splitlines()
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
            depends_on = list(depends_on_raw.keys()) if isinstance(depends_on_raw, dict) else list(depends_on_raw)

            # Render the service block as YAML for the symbol source
            svc_source = yaml.dump(
                {svc_name: svc_cfg},
                default_flow_style=False,
                allow_unicode=True,
            ).rstrip()

            # Build a readable signature
            if image:
                signature = f"service {svc_name}: image={image}"
            elif build:
                ctx = build.get("context", ".") if isinstance(build, dict) else str(build)
                signature = f"service {svc_name}: build context={ctx}"
            else:
                signature = f"service {svc_name}"

            start_line = _find_service_line(text_lines, svc_name)

            symbols.append(CodeSymbol(
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
                    "build": (build.get("context") if isinstance(build, dict) else str(build)) if build else None,
                    "ports": ports,
                    "volumes": volumes,
                    "environment": environment,
                    "depends_on": depends_on,
                },
            ))

        return symbols
