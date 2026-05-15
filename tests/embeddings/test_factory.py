from __future__ import annotations

import pytest

import server.embeddings.factory as factory_module
from server.embeddings.factory import (
    close_embedding_provider,
    get_embedding_provider,
    register,
)


class _StubProvider:
    dimensions = 64

    async def embed_batch(self, texts):
        return [[0.0] * 64] * len(texts)

    async def embed_query(self, text):
        return [0.0] * 64


class _StubProviderWithClose(_StubProvider):
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_factory(monkeypatch):
    monkeypatch.setattr(factory_module, "_registry", {})
    monkeypatch.setattr(factory_module, "_provider", None)


def test_register_adds_to_registry():
    register("stub", _StubProvider)
    assert "stub" in factory_module._registry
    assert factory_module._registry["stub"] is _StubProvider


def test_get_embedding_provider_instantiates_registered_class(monkeypatch):
    register("stub", _StubProvider)
    monkeypatch.setattr(
        "server.embeddings.factory.settings.embeddings_provider", "stub"
    )

    provider = get_embedding_provider()

    assert isinstance(provider, _StubProvider)


def test_get_embedding_provider_returns_singleton(monkeypatch):
    register("stub", _StubProvider)
    monkeypatch.setattr(
        "server.embeddings.factory.settings.embeddings_provider", "stub"
    )

    assert get_embedding_provider() is get_embedding_provider()


def test_get_embedding_provider_raises_for_unknown_name(monkeypatch):
    register("stub", _StubProvider)
    monkeypatch.setattr(
        "server.embeddings.factory.settings.embeddings_provider", "unknown"
    )

    with pytest.raises(ValueError, match="unknown"):
        get_embedding_provider()


def test_error_message_lists_registered_providers(monkeypatch):
    register("alpha", _StubProvider)
    register("beta", _StubProvider)
    monkeypatch.setattr(
        "server.embeddings.factory.settings.embeddings_provider", "unknown"
    )

    with pytest.raises(ValueError, match="alpha"):
        get_embedding_provider()


async def test_close_embedding_provider_calls_close_on_provider(monkeypatch):
    provider = _StubProviderWithClose()
    monkeypatch.setattr(factory_module, "_provider", provider)

    await close_embedding_provider()

    assert provider.closed
    assert factory_module._provider is None


async def test_close_embedding_provider_is_noop_when_none():
    await close_embedding_provider()


async def test_close_embedding_provider_skips_close_if_not_defined(monkeypatch):
    monkeypatch.setattr(factory_module, "_provider", _StubProvider())

    await close_embedding_provider()

    assert factory_module._provider is None
