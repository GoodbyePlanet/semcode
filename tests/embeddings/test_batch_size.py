from __future__ import annotations

import pytest

import server.embeddings.jina as jina_module
import server.embeddings.jina_api as jina_api_module
import server.embeddings.ollama as ollama_module
import server.embeddings.openai as openai_module
import server.embeddings.voyage as voyage_module
from server.embeddings.base import _DEFAULT_BATCH_SIZE, EmbeddingProvider

# The pipeline batches symbols up to `batch_size`, so the property must stay in
# lockstep with the `_BATCH_SIZE` each provider passes to `embed_in_batches` —
# otherwise the pipeline packs batches the provider immediately re-splits.
_PROVIDERS = [
    (voyage_module.VoyageEmbeddingProvider, voyage_module, 128),
    (openai_module.OpenAIEmbeddingProvider, openai_module, 128),
    (jina_api_module.JinaApiEmbeddingProvider, jina_api_module, 128),
    (jina_module.JinaEmbeddingProvider, jina_module, 32),
    (ollama_module.OllamaEmbeddingProvider, ollama_module, 32),
]


@pytest.mark.parametrize(("provider_cls", "module", "expected"), _PROVIDERS)
def test_batch_size_matches_module_constant(provider_cls, module, expected) -> None:
    # Read through the descriptor — constructing a provider needs API keys.
    assert provider_cls.batch_size.fget(None) == module._BATCH_SIZE == expected


def test_protocol_default_is_the_conservative_size() -> None:
    assert EmbeddingProvider.batch_size.fget(None) == _DEFAULT_BATCH_SIZE == 32
