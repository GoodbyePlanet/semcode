from __future__ import annotations

from server.parser.dockerfile import DockerfileParser


def test_empty_file_returns_no_symbols():
    assert DockerfileParser().parse_file(b"", "svc/Dockerfile") == []


def test_canonical_multistage_dockerfile(read_fixture):
    src = read_fixture("dockerfile/Dockerfile")
    syms = DockerfileParser().parse_file(src, "svc/Dockerfile")

    stages = [s for s in syms if s.symbol_type == "stage"]
    stage_names = [s.name for s in stages]
    assert stage_names == ["builder", "runtime"]
    assert stages[0].extras["base_image"] == "python:3.12-slim"
    assert stages[0].extras["stage_alias"] == "builder"
    assert stages[1].extras["exposed_ports"] == ["8000"]
    assert stages[1].extras["entrypoint"] is not None
    assert stages[1].extras["cmd"] is not None

    by_type: dict[str, list] = {}
    for s in syms:
        by_type.setdefault(s.symbol_type, []).append(s)

    assert {
        "stage",
        "copy_instruction",
        "run_instruction",
        "env_var",
        "expose",
        "entrypoint",
        "cmd",
    } <= set(by_type)

    env_var = by_type["env_var"][0]
    assert env_var.name == "PORT"
    assert env_var.parent_name == "runtime"

    expose = by_type["expose"][0]
    assert expose.parent_name == "runtime"
    assert expose.extras["ports"] == ["8000"]

    for s in syms:
        assert s.language == "dockerfile"
