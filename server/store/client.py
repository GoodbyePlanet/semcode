from __future__ import annotations

import ipaddress
import warnings
from urllib.parse import urlsplit

from qdrant_client import AsyncQdrantClient

from server.config import Settings, settings

# qdrant-client warns on every client built with an API key over plain http, including
# loopback. semcode builds several clients, so that warning is silenced here and the
# startup check in server.main logs a single, more specific one instead.
_INSECURE_KEY_WARNING = "Api key is used with an insecure connection"


def make_qdrant_client(cfg: Settings = settings) -> AsyncQdrantClient:
    """Build the Qdrant client every store uses, so URL and auth can't drift."""
    kwargs: dict[str, str] = {"url": cfg.qdrant_url}
    if cfg.qdrant_api_key is not None:
        kwargs["api_key"] = cfg.qdrant_api_key.get_secret_value()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=_INSECURE_KEY_WARNING, category=UserWarning
        )
        return AsyncQdrantClient(**kwargs)


def is_cleartext_remote(url: str) -> bool:
    """True when `url` is plain http to a host that may be reached over a network.

    Loopback hosts and single-label hostnames (compose/k8s service names such as
    `qdrant`) are treated as local or private and don't count.
    """
    # Mirror qdrant-client, which accepts a scheme-less `localhost:6333`.
    if "//" not in url:
        url = f"//{url}"
    parts = urlsplit(url)
    if parts.scheme == "https":
        return False
    host = (parts.hostname or "").lower()
    if not host or host == "localhost":
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return "." in host
