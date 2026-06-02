# Sparse Vector Embeddings (BM25)

This document covers how semcode produces sparse BM25 vectors for code symbols: why BM25 complements dense embeddings, the code-identifier tokenizer pre-processing step, the distinction between passage and query encoding, and the sparse vector format stored in Qdrant.

---

## Overview

Sparse embeddings power the keyword matching half of semcode's hybrid search. BM25 (Best Match 25) is a classic term-frequency ranking function that scores documents based on exact term overlap between the query and the document. It complements dense semantic search in cases where exact or near-exact identifier names matter more than conceptual similarity:

- A query for `PlaceOrderRequest` should find the class with that exact name, even if semantically similar classes exist
- A query for `processRefund` should match even if no dense model was trained on that specific domain term

At index time, each `CodeSymbol`'s source text is converted to a sparse vector. At query time, the search string is converted to a sparse query vector. Qdrant's RRF fusion then combines the dense and sparse rankings (see [retrieval-rrf.md](retrieval-rrf.md)).

---

## BM25SparseProvider

`BM25SparseProvider` (`server/embeddings/bm25.py`) is the only sparse provider. Unlike the dense provider, it is not pluggable — BM25 is hardwired and there is no `SPARSE_EMBEDDINGS_PROVIDER` configuration.

The provider uses the [`fastembed`](https://github.com/qdrant/fastembed) library with the `Qdrant/bm25` model:

```python
self._model = Bm25("Qdrant/bm25")
```

A singleton is available via `get_sparse_embedding_provider()`. Like the dense singleton, it is created on first call and held for the process lifetime.

**Execution model:** `fastembed`'s `Bm25` model is synchronous and CPU-bound. Both `embed_batch` and `embed_query` run the model in a thread executor to avoid blocking the async event loop:

```python
embeddings = await loop.run_in_executor(
    None, lambda: list(self._model.passage_embed(prepared))
)
```

---

## Code Tokenizer Pre-processing

Before any text reaches the BM25 model, it is pre-processed by `split_code_identifiers()` (`server/embeddings/code_tokenizer.py`). This step exists because BM25 operates on word tokens — without splitting, camelCase and snake_case identifiers are treated as single opaque tokens that only match queries written in the exact same style.

The function applies four transformations in sequence:

| Step | Input | Output |
|------|-------|--------|
| camelCase / PascalCase split | `placeOrder` | `place Order` |
| Consecutive caps split | `XMLParser` | `XML Parser` |
| Underscore split | `place_order` | `place order` |
| Hyphen split | `place-order` | `place order` |

Crucially, the function returns **both** the original text and the expanded text, concatenated:

```python
return text + "\n" + expanded
```

This means the BM25 index contains both the original identifier (`PlaceOrderRequest`) and its split form (`Place Order Request`). A query for either form will match — exact identifier lookup and natural-language keyword search are both supported by the same index.

---

## Passage vs Query Embedding

BM25 uses different statistics for indexing documents versus scoring queries. `BM25SparseProvider` exposes both:

| Method | fastembed call | Use |
|--------|---------------|-----|
| `embed_batch(texts)` | `model.passage_embed(prepared)` | Index time — all symbols in a file |
| `embed_query(text)` | `model.query_embed(prepared)` | Search time — the user's query string |

Both paths apply `split_code_identifiers` before calling the model.

---

## Sparse Vector Structure

Both methods return `SparseVector` objects from the `qdrant_client` library:

```python
SparseVector(
    indices=[42, 187, 903, ...],   # vocabulary token IDs (non-zero terms only)
    values=[0.34, 0.81, 0.12, ...] # BM25 weights for each term
)
```

Only terms with non-zero weight are stored — hence "sparse." A typical code symbol produces a vector with tens to hundreds of non-zero entries out of a vocabulary of thousands.

### Qdrant Collection Configuration

The sparse vector is stored under the `text-sparse` named vector with:

```python
SparseVectorParams(index=SparseIndexParams(on_disk=False))
```

`on_disk=False` means the sparse index lives entirely in RAM, not on disk. This trades memory usage for lower lookup latency. For a large codebase with many indexed symbols, the in-memory sparse index can grow significantly.

---

## Observations

**No configuration path for the sparse provider** — BM25 is hardwired. Unlike the dense provider (where `EMBEDDINGS_PROVIDER` selects from five options), there is no way to substitute a different sparse model (e.g., SPLADE) without code changes.

**In-memory sparse index** — `on_disk=False` is not configurable. On very large codebases, the sparse index memory footprint may become a concern. Qdrant supports `on_disk=True` for sparse vectors, but switching requires dropping and recreating the collection.

**BM25 text excludes metadata** — the text passed to BM25 (`_build_bm25_text`) contains only `signature + docstring + source`. The rich metadata preamble used for dense embeddings (service name, language, symbol type, HTTP routes) is absent. A keyword search for "POST /orders" or "Java method" will not match via the sparse path unless those strings appear literally in the source code.

**Expanded form affects IDF statistics** — `split_code_identifiers` appends the expanded form, making each document approximately twice as long as the raw source. BM25's document length normalization (the `b` parameter in the BM25 formula) is computed over this expanded length, which may reduce scores for long symbols relative to what they would be with raw text.
