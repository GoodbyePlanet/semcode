from __future__ import annotations

import pytest

from server.config import Settings


def test_embedding_max_chars_defaults_to_8k_token_providers() -> None:
    for provider in ("jina", "jina-api", "openai"):
        settings = Settings(_env_file=None, EMBEDDINGS_PROVIDER=provider)
        assert settings.embedding_max_chars == 22000


def test_embedding_max_chars_defaults_higher_for_voyage() -> None:
    settings = Settings(_env_file=None, EMBEDDINGS_PROVIDER="voyage")
    assert settings.embedding_max_chars == 86000


def test_embedding_max_chars_defaults_lower_for_ollama() -> None:
    settings = Settings(_env_file=None, EMBEDDINGS_PROVIDER="ollama")
    assert settings.embedding_max_chars == 5500


def test_embedding_max_chars_explicit_override_wins() -> None:
    settings = Settings(
        _env_file=None, EMBEDDINGS_PROVIDER="voyage", EMBEDDING_MAX_CHARS=12345
    )
    assert settings.embedding_max_chars == 12345


def test_load_services_returns_empty_when_config_file_missing() -> None:
    settings = Settings(_env_file=None, CONFIG_PATH="/nonexistent/config.yaml")
    assert settings.load_services() == []


def test_load_services_returns_empty_for_empty_file(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("")
    settings = Settings(_env_file=None, CONFIG_PATH=str(config_path))
    assert settings.load_services() == []


def test_load_services_parses_services_from_file(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("services:\n  - name: svc\n    github_repo: org/svc\n")
    settings = Settings(_env_file=None, CONFIG_PATH=str(config_path))
    services = settings.load_services()
    assert len(services) == 1
    assert services[0].name == "svc"
    assert services[0].github_repo == "org/svc"


def test_load_services_raises_clear_error_when_config_path_is_a_directory(
    tmp_path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.mkdir()
    settings = Settings(_env_file=None, CONFIG_PATH=str(config_path))

    with pytest.raises(RuntimeError, match="is a directory, not a file"):
        settings.load_services()
