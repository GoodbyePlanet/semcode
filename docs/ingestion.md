# Ingestion Pipeline

This document covers how semcode indexes code from GitHub repositories into Qdrant, including incremental change detection and stale-entry cleanup.

---

## Overview

Ingestion is managed by `IndexPipeline` (`server/indexer/pipeline.py`). For each configured service, the pipeline:

1. Discovers all indexable files from GitHub
2. Skips files whose content hasn't changed since the last index run
3. Downloads changed file content, parses it into `CodeSymbol` entries, generates dense and sparse embeddings, and upserts them into Qdrant
4. Removes index entries for files that have been deleted from the repository

The pipeline is triggered via the `/reindex` HTTP endpoint (streaming NDJSON progress) or the `index_all` MCP admin tool.

---

## Pipeline Stages

### 1. Discovery

`list_github_files()` (`server/indexer/github_source.py`) issues a single recursive request to the GitHub Trees API:

```
GET /repos/{org}/{repo}/git/trees/{ref}?recursive=1
```

This returns the full file tree in one round-trip. Each entry is filtered by three criteria — all three must pass:

| Filter | Mechanism |
|--------|-----------|
| **Supported extension** | `is_supported_path(path)` — parser registry knows which extensions are indexable |
| **Root prefix** | If `ServiceConfig.root` is set, only paths under that prefix are considered |
| **Exclude patterns** | `ServiceConfig.exclude` glob patterns (fnmatch, checked against both full path and basename) |

Surviving files become `GitHubFile(rel_path, blob_sha)` objects. The `blob_sha` is the git blob SHA — a content fingerprint that drives incremental indexing in the next stage.

> **Large-repo fallback:** The GitHub Trees API has an undocumented response size limit. When a repo's tree exceeds it, GitHub sets `truncated: true` and returns only a partial tree. In that case `list_github_files` falls back to a recursive per-subtree walk — fetching `git/trees/<sha>` for each directory (non-recursive, so each listing stays well under the limit), pruning subtrees outside `root`, and fetching siblings concurrently. This guarantees no files are silently dropped from large repos.

### 2. Incremental Check

Before downloading anything, the pipeline loads every stored `{file_path → blob_sha}` pair from Qdrant in a paginated scroll:

```python
existing_hashes = await self._store.get_indexed_file_hashes(svc.name)
```

For each discovered file, the current `blob_sha` is compared against the stored value. If they match, the file is skipped — no download, no re-parsing, no re-embedding. This makes incremental runs cheap: only files whose content has actually changed incur network and CPU cost.

File paths are stored as `{service_name}/{path_in_repo}` (e.g., `catalog-service/src/main/java/Foo.java`), prefixed with the service name to prevent collisions when multiple services share a Qdrant collection.

### 3. Content Fetch

Changed files are fetched by blob SHA (not by path + ref):

```python
content = await fetch_blob_content(
    settings.github_token,
    svc.github_repo,
    f.blob_sha,
    client=http_client,
)
```

Fetching by blob SHA is more efficient than path-based fetching during indexing: the SHA is already known from the tree response, and the blob API is a direct content lookup with no ref resolution overhead.

### 4. Parsing

`parse_file(content, stored_path)` dispatches to the language-specific parser via the registry. The result is a `list[CodeSymbol]` — one entry per indexable symbol (class, method, function, interface, etc.).

If a file produces no symbols (empty, unsupported format, or parse failure), any existing index entries for that file are cleaned up and the file is skipped.

### 5. Embedding Text Construction

Two separate texts are produced per symbol — one for dense embeddings, one for sparse (BM25) embeddings. The strategies differ deliberately:

#### Dense: `_build_embedding_text`

Produces a rich metadata preamble followed by the symbol's source. This text is designed to be semantically rich so the dense model can embed it into a meaningful vector:

```
Python method `process_order` in class `OrderService` (service: catalog-service)
Package/module: com.example.orders
HTTP endpoint: POST /orders
Annotations: @PostMapping, @Transactional
Processes an order and emits an OrderPlaced event...  ← docstring (first 300 chars)

def process_order(self, order: Order) -> Result:     ← signature
    # full source code...                            ← source (fills remaining budget)
```

Metadata included (when present): language, symbol type, name, parent class, service name, package, Spring stereotypes, HTTP method/route, annotations (first 8), Lombok annotations, React.memo flag, docstring.

The whole embedding text (preamble + signature + docstring + source) is budgeted to **`EMBEDDING_MAX_CHARS`** (default **6,000** chars, ~1,500 tokens). The metadata preamble and signature consume the budget first; the source fills whatever remains. When a symbol's source exceeds its budget it is truncated with a `// ... (truncated)` marker **and a `WARNING` is logged** (naming the symbol and file) so the loss is observable. Raise `EMBEDDING_MAX_CHARS` for providers that accept larger inputs — see [configuration.md](configuration.md).

> **Future direction — sub-chunking (deferred):** Truncation still drops the tail of a genuinely oversized symbol (e.g. a 1,000-line class) from the *dense* vector; BM25 and the stored payload keep the full source. A complete fix would split such symbols into overlapping windows and emit multiple dense points each. That was deferred because it requires a chunk index in the point ID (`store/qdrant.py`, `_symbol_point_id`) and search-result dedup so sub-chunks of one symbol don't crowd results. Watch the truncation warnings to judge whether it's worth it.

#### Sparse: `_build_bm25_text`

Simpler — only the functional code text, no metadata preamble:

```
signature + docstring + source
```

This text is then pre-processed by `split_code_identifiers` (see [sparse-vectors.md](sparse-vectors.md)) before BM25 encoding.

### 6. Embedding

Both embedding calls are made sequentially per file batch:

```python
dense_vectors = await self._embedder.embed_batch(texts_dense)
sparse_vectors = await self._sparse_embedder.embed_batch(texts_sparse)
```

If either call raises an exception, the file is skipped and existing index entries are preserved until the next successful run.

### 7. Upsert

Before inserting new vectors, all existing entries for the file are removed:

```python
await self._store.delete_by_file(svc.name, stored_path)
await self._store.upsert_chunks(payloads, dense_vectors, sparse_vectors)
```

This ensures clean replacement when symbols are added, removed, or renamed within a file. Each point's ID is a deterministic `uuid5` derived from `service:file_path:symbol_name:start_line`, so symbols moving to a new line produce new IDs (handled correctly by the delete-first approach).

Each point carries a payload with 20+ fields (see Data Model below).

### 8. Stale Cleanup

After all files are processed, the pipeline identifies paths that were in the previous index but are no longer present in the current GitHub tree (deleted files):

```python
stale_paths = [p for p in existing_hashes if p not in all_stored_paths]
for stale_path in stale_paths:
    await self._store.delete_by_file(svc.name, stale_path)
```

---

## Incremental Indexing in Detail

The blob SHA acts as a zero-download change detector. The GitHub Trees API returns a blob SHA per file as part of the tree enumeration — no file download is needed to determine whether content has changed.

A forced reindex (`force=True`) bypasses the SHA comparison and reindexes every file.

---

## Data Model

### `CodeSymbol` (parsed representation)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Symbol name (e.g., `processOrder`) |
| `symbol_type` | `str` | `class`, `method`, `function`, `interface`, `enum`, `record`, `hook`, `component`, `type` |
| `language` | `str` | `java`, `python`, `typescript`, `go`, etc. |
| `source` | `str` | Raw source text of the symbol |
| `file_path` | `str` | `{service_name}/{path_in_repo}` |
| `start_line` / `end_line` | `int` | Line range in the file |
| `parent_name` | `str \| None` | Enclosing class/module name |
| `package` | `str \| None` | Java package or Python module path |
| `annotations` | `list[str]` | Decorator/annotation names |
| `signature` | `str` | Declaration line |
| `docstring` | `str \| None` | Documentation string |
| `extras` | `dict` | Language-specific metadata (Spring stereotypes, HTTP routes, Lombok annotations, React flags) |

### Qdrant Payload (stored per point)

All `CodeSymbol` fields are stored verbatim, plus:

| Field | Description |
|-------|-------------|
| `service` | Service name |
| `chunk_tier` | `"method"` if symbol has a parent, `"class"` otherwise |
| `file_hash` | blob SHA — the content fingerprint used for incremental indexing |
| `indexed_at` | ISO 8601 UTC timestamp of when this symbol was indexed |

---

## Observations

**Sequential embedding calls** — `embed_batch` for dense and `embed_batch` for sparse are awaited sequentially. They are independent operations targeting different providers; wrapping them in `asyncio.gather` would reduce per-file embedding latency by ~50%.

**No embedding retry** — a transient API error on either embedding call causes the file to be silently skipped, leaving its existing index stale indefinitely. There is no exponential backoff or retry queue. Reindexing requires either a force reindex or waiting for the file's content to change.

**BM25 text excludes metadata** — `_build_bm25_text` produces only `signature + docstring + source`. Metadata present in the dense text (service name, language, symbol type) is absent. A BM25 query for "Python method" will not match unless the word "Python" or "method" appears in the source code itself.

**delete-before-upsert gap** — The pipeline deletes all entries for a file before upserting the new ones. If the process is interrupted between delete and upsert, the file has no index entries. The next incremental run will redownload and reindex the file correctly — but until then, queries miss the file entirely.

**GitHub Trees truncation** — Very large repositories may have their tree response silently truncated by the GitHub API. The pipeline logs a warning but does not retry or paginate to recover the missing entries.

**Dense-embedding truncation drops the tail of huge symbols** — The embedding text is budgeted to `EMBEDDING_MAX_CHARS` (configurable, default 6,000). A symbol larger than the budget has its tail excluded from the *dense* vector (BM25 and the stored source keep everything), so semantic search over that tail relies on BM25 alone. Truncation now emits a `WARNING`; the deferred sub-chunking fix is described in the [Embedding Text Construction](#5-embedding-text-construction) section above.
