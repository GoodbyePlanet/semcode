from __future__ import annotations

import asyncio

from fastembed.sparse.bm25 import Bm25
from qdrant_client.models import SparseVector

from server.embeddings.code_tokenizer import split_code_identifiers

_provider: BM25SparseProvider | None = None


class BM25SparseProvider:
    def __init__(self) -> None:
        self._model = Bm25("Qdrant/bm25")

    async def embed_batch(self, texts: list[str]) -> list[SparseVector]:
        prepared = [split_code_identifiers(t) for t in texts]
        loop = asyncio.get_running_loop()
        embeddings = await loop.run_in_executor(
            None, lambda: list(self._model.passage_embed(prepared))
        )
        return [
            SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
            for e in embeddings
        ]

    async def embed_query(self, text: str) -> SparseVector:
        prepared = split_code_identifiers(text)
        loop = asyncio.get_running_loop()
        [embedding] = await loop.run_in_executor(
            None, lambda: list(self._model.query_embed(prepared))
        )
        return SparseVector(indices=embedding.indices.tolist(), values=embedding.values.tolist())


def get_sparse_embedding_provider() -> BM25SparseProvider:
    global _provider
    if _provider is None:
        _provider = BM25SparseProvider()
    return _provider


async def close_sparse_embedding_provider() -> None:
    global _provider
    _provider = None
