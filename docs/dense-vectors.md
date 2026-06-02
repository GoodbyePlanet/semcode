# Dense Vector Embeddings

This document covers how semcode produces dense (floating-point) embedding vectors for code symbols: the provider abstraction, the text construction strategy used at index time, and the five supported embedding backends.

---

## Overview

Dense embeddings power the semantic half of semcode's hybrid search. At index time, each `CodeSymbol` is converted to a rich text representation and passed to a configured embedding provider, which returns a fixed-length floating-point vector. This vector is stored in Qdrant under the `text-dense` named vector. At query time, the natural-language search query is embedded using the same provider and used as the dense component in the hybrid RRF search (see [retrieval-rrf.md](retrieval-rrf.md)).

---

## Provider Protocol

All dense embedding providers implement the `EmbeddingProvider` Protocol (`server/embeddings/base.py`):

```python
class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
```

- `embed_batch` is used at **index time** — it receives the prepared texts for all symbols in a file and returns one vector per text.
- `embed_query` is used at **query time** — it receives the user's search string and returns a single vector.

Some providers (jina-api, voyage) encode passages and queries differently (asymmetric retrieval). The Protocol makes this distinction available without callers needing to know which provider is active.

---

## Factory and Provider Selection

Providers register themselves by name at module import time (`server/embeddings/factory.py`):

```python
# At the bottom of each provider file:
from server.embeddings.factory import register
register("voyage", VoyageEmbeddingProvider)
```

`get_embedding_provider()` creates and caches a singleton on first call, reading the provider name from the `EMBEDDINGS_PROVIDER` environment variable. Once created, the singleton is held for the lifetime of the process — switching providers requires a process restart.

All five provider modules are imported at server startup (`server/embeddings/__init__.py`), which triggers their `register()` calls and populates the registry before the first embedding request.

---

## Embedding Text Strategy

The text sent to the dense provider is built by `_build_embedding_text()` (`server/indexer/pipeline.py`). It produces a structured natural-language representation of each symbol designed to maximise semantic richness:

```
{language} {symbol_type} `{name}` [in class `{parent_name}`] (service: {service_name})
Package/module: {package}
Spring stereotype: {stereotype}          ← if present
HTTP endpoint: {http_method} {route}     ← if present
Annotations: @Foo, @Bar, ...             ← up to 8 annotations
Lombok: @Builder, @Data, ...             ← if present
Wrapped in React.memo for performance.   ← if present

{docstring[:300]}                        ← documentation (first 300 chars)

{signature}                              ← declaration line
{source[:6000]}                          ← full source (hard-truncated)
```

**Why the preamble?** Dense models embed the meaning of the full text, not just keyword frequency. By prepending metadata (service name, type, annotations) the model can place semantically similar symbols — regardless of language or framework — near each other in vector space. A query like "find the service that handles order placement" can match a `@PostMapping("/orders")` Java method even if the word "order" doesn't appear in the method body.

**Source truncation:** Source is hard-capped at **6,000 characters** (~1,500 tokens). Symbols longer than this are truncated with a `// ... (truncated)` marker. The limit is the constant `_MAX_EMBEDDING_CHARS` in `pipeline.py`.

---

## Supported Providers

| Name | Type | Default model | Default dims | Asymmetric | Rate-limit retry |
|------|------|---------------|--------------|------------|-----------------|
| `jina` | Self-hosted (TEI) | `jinaai/jina-embeddings-v2-base-code` | 768 | No | No |
| `jina-api` | Hosted API | `jina-embeddings-v2-base-code` | 768 | Yes | Yes (4 attempts) |
| `voyage` | Hosted API | `voyage-code-3` | 1024 | Yes | Yes (4 attempts) |
| `openai` | Hosted API | `text-embedding-3-large` | 3072 | No | Yes (4 attempts) |
| `ollama` | Self-hosted | `nomic-embed-text` | 768 | No | No |

### `jina` (default)

Self-hosted Jina Code V2 model served via [HuggingFace Text Embeddings Inference (TEI)](https://github.com/huggingface/text-embeddings-inference). Calls `POST {JINA_URL}/embed` with `{"inputs": [...]}`. TEI returns a plain list of vectors; an OpenAI-style `{"data": [...]}` response is also accepted as a fallback. Batch size: 32. No rate-limit handling.

### `jina-api`

Jina AI's hosted API (`api.jina.ai`). Supports **asymmetric encoding**: passages (indexed symbols) are sent with `task=retrieval.passage`; queries are sent with `task=retrieval.query`. For the newer `jina-code-embeddings-*` model family, these tasks are remapped to `nl2code.passage` / `nl2code.query` — natural language to code retrieval. Input text is sanitized before sending (lone surrogates and control characters removed). Rate-limit retries: 4 attempts with backoff delays of 10, 20, 30, 40 seconds. Supports Matryoshka dimension truncation via `JINA_API_DIMENSIONS`.

### `voyage`

Voyage AI's hosted API. **Asymmetric encoding**: `input_type=document` for passages, `input_type=query` for queries. Default model `voyage-code-3` is purpose-built for code retrieval. Rate-limit retries: 4 attempts. Dimension override supported via `VOYAGE_DIMENSIONS`.

### `openai`

OpenAI's Embeddings API. **Symmetric**: `embed_batch` and `embed_query` use the same code path (no passage/query distinction). Default model `text-embedding-3-large` (3072 dimensions) supports Matryoshka truncation via `OPENAI_DIMENSIONS`. Rate-limit retries: 4 attempts.

### `ollama`

Self-hosted [Ollama](https://ollama.com) instance. Calls `POST {OLLAMA_URL}/api/embed`. **Symmetric**: `embed_query` delegates to `embed_batch([text])`. Batch size: 32. No rate-limit handling. Default model `nomic-embed-text` (768 dims); other models require setting `OLLAMA_DIMENSIONS`.

---

## Observations

**No provider reset path** — the singleton is created once and held for the process lifetime. To switch providers (e.g., from `jina` to `voyage`), the server must be restarted. There is no hot-reload or per-request provider selection.

**Dimension mismatch causes server startup failure** — `ensure_collection()` is called in the server's lifespan context (`server/main.py:39`) at boot, before any requests are served. If the configured provider's dimensions don't match the existing Qdrant collection, a `RuntimeError` is raised and the server fails to start. This is an intentional hard stop — the server refuses to come up with a mismatched index rather than silently serving stale vectors.

**Inconsistent rate-limit handling** — the three hosted API providers (jina-api, voyage, openai) implement 429 backoff with 4 attempts. The two self-hosted providers (jina, ollama) do not — a transient local service error raises immediately.

**No connection pool configuration** — each provider creates one `httpx.AsyncClient` with a 120-second timeout and default connection limits. There is no way to configure pool size, keep-alive behavior, or per-host connection limits.

**Symmetric vs asymmetric retrieval** — jina-api and voyage use separate encoding modes for passages and queries, which generally improves retrieval quality for code search. The other three providers use the same path for both, which means the model cannot distinguish "I am embedding a document" from "I am embedding a query."
