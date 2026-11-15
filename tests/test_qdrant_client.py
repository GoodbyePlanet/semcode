from __future__ import annotations

import warnings
from unittest.mock import MagicMock, patch

import pytest

from server.config import Settings
from server.store import client as client_module
from server.store.client import is_cleartext_remote, make_qdrant_client
from server.store.commit_store import CommitStore
from server.store.qdrant import QdrantStore
from server.store.service_registry import ServiceRegistry


def test_passes_api_key_when_set() -> None:
    cfg = Settings(
        _env_file=None, QDRANT_URL="https://q.example.com", QDRANT_API_KEY="k"
    )

    with patch.object(client_module, "AsyncQdrantClient") as ctor:
        make_qdrant_client(cfg)

    ctor.assert_called_once_with(url="https://q.example.com", api_key="k")


def test_omits_api_key_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    cfg = Settings(_env_file=None, QDRANT_URL="http://localhost:6333")

    with patch.object(client_module, "AsyncQdrantClient") as ctor:
        make_qdrant_client(cfg)

    ctor.assert_called_once_with(url="http://localhost:6333")


def test_silences_client_insecure_key_warning() -> None:
    """qdrant-client warns per client on http + key; the startup check replaces it."""
    cfg = Settings(
        _env_file=None, QDRANT_URL="http://localhost:6333", QDRANT_API_KEY="k"
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        make_qdrant_client(cfg)

    assert not [w for w in caught if "insecure connection" in str(w.message)]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:6333", False),
        ("http://127.0.0.1:6333", False),
        ("http://[::1]:6333", False),
        ("http://qdrant:6333", False),
        ("localhost:6333", False),
        ("https://x.cloud.qdrant.io:6333", False),
        ("http://qdrant.example.com:6333", True),
        ("http://10.0.0.5:6333", True),
    ],
)
def test_is_cleartext_remote(url: str, expected: bool) -> None:
    assert is_cleartext_remote(url) is expected


@pytest.mark.parametrize(
    ("module", "build"),
    [
        ("server.store.qdrant", lambda: QdrantStore(dimensions=8)),
        ("server.store.commit_store", lambda: CommitStore(dimensions=8)),
        ("server.store.service_registry", ServiceRegistry),
    ],
)
def test_every_store_uses_the_shared_factory(module: str, build) -> None:
    sentinel = MagicMock()
    with patch(f"{module}.make_qdrant_client", return_value=sentinel) as factory:
        store = build()

    factory.assert_called_once_with()
    assert store._client is sentinel
