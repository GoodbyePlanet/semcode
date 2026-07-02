from __future__ import annotations

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
