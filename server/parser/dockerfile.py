from __future__ import annotations

import re

from server.parser.base import CodeSymbol

# Instructions the task requires as indexable symbols
_INDEXED_INSTRUCTIONS = {"FROM", "RUN", "COPY", "ENTRYPOINT", "CMD", "ENV", "EXPOSE"}


def _logical_lines(raw_lines: list[str]) -> list[tuple[int, str]]:
    """Merge continuation lines (trailing backslash) into single logical lines.

    Returns a list of (start_line_0indexed, merged_text) tuples.
    """
    result: list[tuple[int, str]] = []
    buf_parts: list[str] = []
    buf_start = 0

    for i, line in enumerate(raw_lines):
        rstripped = line.rstrip()
        if rstripped.endswith("\\"):
            if not buf_parts:
                buf_start = i
            buf_parts.append(rstripped[:-1].rstrip())
        else:
            if buf_parts:
                buf_parts.append(rstripped.strip())
                result.append((buf_start, " ".join(p for p in buf_parts if p)))
                buf_parts = []
            else:
                result.append((i, rstripped))

    if buf_parts:
        result.append((buf_start, " ".join(p for p in buf_parts if p)))

    return result


def _parse_instruction(text: str) -> tuple[str, str] | None:
    """Split 'INSTRUCTION value' into (INSTRUCTION_UPPER, value). Returns None for blank/comment lines."""
    stripped = text.strip()
    if not stripped or stripped.startswith("#"):
        return None
    m = re.match(r"^([A-Za-z]+)\s*(.*)", stripped, re.DOTALL)
    if not m:
        return None
    return m.group(1).upper(), m.group(2).strip()


class DockerfileParser:
    def supported_extensions(self) -> list[str]:
        return []

    def language(self) -> str:
        return "dockerfile"

    def supported_filenames(self) -> list[str]:
        return ["Dockerfile", "dockerfile"]

    def parse_file(self, source: bytes, file_path: str) -> list[CodeSymbol]:
        text = source.decode("utf-8", errors="replace")
        raw_lines = text.splitlines()
        logical = _logical_lines(raw_lines)
        symbols: list[CodeSymbol] = []

        # ── Split into stages at each FROM instruction ─────────────────────────
        # Each stage: (start_line_0idx, base_image, alias | None, [(line_0idx, text), ...])
        stages: list[tuple[int, str, str | None, list[tuple[int, str]]]] = []
        cur_lines: list[tuple[int, str]] = []
        cur_start = 0
        cur_base: str | None = None
        cur_alias: str | None = None

        for line_no, line_text in logical:
            parsed = _parse_instruction(line_text)
            if parsed and parsed[0] == "FROM":
                if cur_base is not None:
                    stages.append((cur_start, cur_base, cur_alias, cur_lines))
                value = parsed[1]
                m = re.match(r"(\S+)(?:\s+AS\s+(\S+))?", value, re.IGNORECASE)
                cur_base = m.group(1) if m else value
                cur_alias = m.group(2) if m else None
                cur_start = line_no
                cur_lines = [(line_no, line_text)]
            elif cur_base is not None:
                cur_lines.append((line_no, line_text))

        if cur_base is not None:
            stages.append((cur_start, cur_base, cur_alias, cur_lines))

        # ── Emit one symbol per stage + per indexed instruction within it ───────
        for stage_idx, (stage_start, base_image, alias, stage_lines) in enumerate(stages):
            stage_name = alias if alias else f"stage-{stage_idx}"
            end_line_0 = stage_lines[-1][0] if stage_lines else stage_start
            stage_source = "\n".join(ln for _, ln in stage_lines)

            # Collect stage-level metadata for extras
            exposed_ports: list[str] = []
            env_vars: list[str] = []
            entrypoint: str | None = None
            cmd: str | None = None

            for _, ln in stage_lines:
                p = _parse_instruction(ln)
                if not p:
                    continue
                instr, val = p
                if instr == "EXPOSE":
                    exposed_ports.extend(val.split())
                elif instr == "ENV":
                    env_vars.append(val)
                elif instr == "ENTRYPOINT":
                    entrypoint = val
                elif instr == "CMD":
                    cmd = val

            # Stage symbol (FROM … AS …)
            symbols.append(CodeSymbol(
                name=stage_name,
                symbol_type="stage",
                language="dockerfile",
                source=stage_source,
                file_path=file_path,
                start_line=stage_start + 1,
                end_line=end_line_0 + 1,
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

            # Per-instruction symbols (skip FROM itself — already captured as stage)
            for line_no, ln in stage_lines:
                p = _parse_instruction(ln)
                if not p:
                    continue
                instr, val = p
                if instr not in _INDEXED_INSTRUCTIONS or instr == "FROM":
                    continue

                if instr == "ENV":
                    var_name = re.split(r"[=\s]", val, 1)[0] if val else "ENV"
                    symbols.append(CodeSymbol(
                        name=var_name,
                        symbol_type="env_var",
                        language="dockerfile",
                        source=ln.strip(),
                        file_path=file_path,
                        start_line=line_no + 1,
                        end_line=line_no + 1,
                        parent_name=stage_name,
                        package=None,
                        annotations=[],
                        signature=ln.strip(),
                        extras={"instruction": "ENV", "value": val},
                    ))

                elif instr == "EXPOSE":
                    symbols.append(CodeSymbol(
                        name=val,
                        symbol_type="expose",
                        language="dockerfile",
                        source=ln.strip(),
                        file_path=file_path,
                        start_line=line_no + 1,
                        end_line=line_no + 1,
                        parent_name=stage_name,
                        package=None,
                        annotations=[],
                        signature=ln.strip(),
                        extras={"instruction": "EXPOSE", "ports": val.split()},
                    ))

                elif instr == "ENTRYPOINT":
                    symbols.append(CodeSymbol(
                        name="ENTRYPOINT",
                        symbol_type="entrypoint",
                        language="dockerfile",
                        source=ln.strip(),
                        file_path=file_path,
                        start_line=line_no + 1,
                        end_line=line_no + 1,
                        parent_name=stage_name,
                        package=None,
                        annotations=[],
                        signature=ln.strip(),
                        extras={"instruction": "ENTRYPOINT", "value": val},
                    ))

                elif instr == "CMD":
                    symbols.append(CodeSymbol(
                        name="CMD",
                        symbol_type="cmd",
                        language="dockerfile",
                        source=ln.strip(),
                        file_path=file_path,
                        start_line=line_no + 1,
                        end_line=line_no + 1,
                        parent_name=stage_name,
                        package=None,
                        annotations=[],
                        signature=ln.strip(),
                        extras={"instruction": "CMD", "value": val},
                    ))

                elif instr == "RUN":
                    run_name = val[:60] + "..." if len(val) > 60 else val
                    symbols.append(CodeSymbol(
                        name=run_name,
                        symbol_type="run_instruction",
                        language="dockerfile",
                        source=ln.strip(),
                        file_path=file_path,
                        start_line=line_no + 1,
                        end_line=line_no + 1,
                        parent_name=stage_name,
                        package=None,
                        annotations=[],
                        signature=ln.strip(),
                        extras={"instruction": "RUN", "command": val},
                    ))

                elif instr == "COPY":
                    parts = val.split()
                    # Strip --from=... flags to find src/dest
                    args = [p for p in parts if not p.startswith("--")]
                    copy_name = f"{args[-2]} → {args[-1]}" if len(args) >= 2 else val
                    symbols.append(CodeSymbol(
                        name=copy_name,
                        symbol_type="copy_instruction",
                        language="dockerfile",
                        source=ln.strip(),
                        file_path=file_path,
                        start_line=line_no + 1,
                        end_line=line_no + 1,
                        parent_name=stage_name,
                        package=None,
                        annotations=[],
                        signature=ln.strip(),
                        extras={"instruction": "COPY", "value": val},
                    ))

        return symbols
