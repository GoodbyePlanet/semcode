from __future__ import annotations

from typing import Protocol, runtime_checkable

# Conservative ceiling for providers that do not declare their own. Matches the
# smallest batch size any bundled provider uses (jina TEI, ollama).
_DEFAULT_BATCH_SIZE = 32


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...

    @property
    def batch_size(self) -> int:
        """Max texts the provider accepts per request.

        Concrete default rather than `...` — every bundled provider subclasses
        this Protocol, so an ellipsis body would silently return None for any
        provider that forgot to override it.
        """
        return _DEFAULT_BATCH_SIZE

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...
