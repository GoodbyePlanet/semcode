---
id: ingestion
title: Ingestion Pipeline
sidebar_position: 3
---

# Ingestion Pipeline

This document covers how semcode indexes code from GitHub repositories into Qdrant, including incremental change detection and stale-entry cleanup.

---

## Overview

Ingestion is managed by `IndexPipeline` (`server/indexer/pipeline.py`). For each configured service, the pipeline:

1. Discovers all indexable files from GitHub
2. Skips files whose content hasn't changed since the last index run
3. Downloads changed file content concurrently, parses it into `CodeSymbol` entries, generates dense and sparse embeddings in batches that span multiple files, and upserts them into Qdrant
4. Removes index entries for files that have been deleted from the repository

The pipeline is triggered via the `/reindex` HTTP endpoint (streaming NDJSON progress) or the `index_all` MCP admin tool.
"Configured service" means resolved from `load_effective_services()` — the union of `config.yaml` and the dynamic
service registry (see [configuration.md](configuration.md#dynamic-service-registration)). `POST /reindex`'s
`github_repo` field registers a service in the registry inline, in the same request that triggers indexing for it —
no separate registration step.

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

Fetches run concurrently, bounded by a semaphore (`_FETCH_CONCURRENCY`, default 10 — the same bound `github_source.py` uses for tree walks and commit diffs). Each fetched file is parsed and handed to a bounded queue (`_PARSED_QUEUE_SIZE`), so downloading continues while the previous group of symbols is being embedded. Every request goes through `_gh_get`, which retries rate limits, 5xx, and transport errors. A fetch that still fails logs an error and drops only that file; its existing index entries are preserved.

### 4. Parsing

`parse_file(content, stored_path)` dispatches to the language-specific parser via the registry. The result is a `list[CodeSymbol]` — one entry per indexable symbol (class, method, function, interface, etc.).

Parsing runs on the event loop rather than in a thread pool, deliberately: `registry.py` builds one parser instance per language and shares it across every file, and tree-sitter `Parser` objects are not safe for concurrent use. Moving `parse_file` to a worker thread would be a data race.

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

The whole embedding text (preamble + signature + docstring + source) is budgeted to **`EMBEDDING_MAX_CHARS`**, which defaults to a value derived from the configured `EMBEDDINGS_PROVIDER`'s context window (22,000 chars for the 8K-token providers, 86,000 for Voyage's 32K window, 5,500 for Ollama's 2K window) rather than one global default — see [configuration.md](configuration.md#embedding-provider) for the per-provider table. The metadata preamble and signature consume the budget first; the source fills whatever remains. When a symbol's source exceeds its budget it is truncated with a `// ... (truncated)` marker **and a `WARNING` is logged** (naming the symbol and file) so the loss is observable. Set `EMBEDDING_MAX_CHARS` explicitly to override the derived default.

> **Future direction — sub-chunking (deferred):** Truncation still drops the tail of a genuinely oversized symbol (e.g. a 1,000-line class) from the *dense* vector; BM25 and the stored payload keep the full source. A complete fix would split such symbols into overlapping windows and emit multiple dense points each. That was deferred because it requires a chunk index in the point ID (`store/qdrant.py`, `_symbol_point_id`) and search-result dedup so sub-chunks of one symbol don't crowd results. Watch the truncation warnings to judge whether it's worth it.

#### Sparse: `_build_bm25_text`

No preamble sentence, but folds in the same high-signal identifiers as the dense
preamble so keyword search on an annotation, route, package, or symbol name still
gets sparse matches:

```
name + package + annotations (@-prefixed) + HTTP method/route + signature + docstring + source
```

This text is then pre-processed by `split_code_identifiers` (see [sparse-vectors.md](sparse-vectors.md)) before BM25 encoding.

### 6. Embedding

Symbols are accumulated **across files** until they fill the provider's batch size (`EmbeddingProvider.batch_size` — 128 for Voyage/OpenAI/Jina's hosted API, 32 for self-hosted Jina TEI and Ollama), or until the batch reaches `_MAX_BATCH_CHARS`. A single file usually yields only a handful of symbols, so batching across files is what keeps requests full instead of sending one tiny request per file.

The dense and sparse embeds for a batch run concurrently:

```python
dense, sparse = await asyncio.gather(
    self._embedder.embed_batch(dense_texts),
    self._sparse_embedder.embed_batch(sparse_texts),
)
```

Dense is network-bound and sparse runs in a thread executor, so the two overlap for free.

If a batch call raises, the pipeline retries that batch **file by file**, so a single unembeddable file costs one extra round-trip rather than dropping every file batched alongside it. A file that still fails is skipped, and its existing index entries are preserved until the next successful run.

### 7. Upsert

Writes stay scoped to one file at a time, even though embedding is batched. New vectors are upserted *before* stale ones are deleted, so the file never has zero indexed symbols:

```python
previous_ids = await self._store.get_point_ids_by_file(service_name, stored_path)
new_ids = await self._store.upsert_chunks(payloads, dense, sparse)
await self._store.delete_by_ids(list(previous_ids - set(new_ids)))
```

Each point's ID is a deterministic `uuid5` derived from `service:file_path:symbol_name:start_line`, so symbols moving to a new line produce new IDs and the old ones fall out as stale. Because the ID includes `file_path`, two different files can never produce colliding IDs — which is what makes batching across files safe.

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

**No embedding retry** — a transient API error on either embedding call causes the file to be silently skipped, leaving its existing index stale indefinitely. There is no exponential backoff or retry queue. Reindexing requires either a force reindex or waiting for the file's content to change.

**BM25 text still omits some dense-only metadata** — `_build_bm25_text` folds in name, package, annotations, and HTTP method/route, but the dense preamble's service name, language, and symbol-type phrasing (e.g. "Java method") are still dense-only. A BM25 query for "Python method" will not match unless the word "Python" or "method" appears elsewhere in the folded-in fields or the source code itself.

**GitHub retries are bounded** — `_gh_get` retries rate limits (403/429, waiting for the window named by `Retry-After` / `X-RateLimit-Reset`, capped at 120s), 5xx, and transport errors, for `_GH_ATTEMPTS` attempts total. A failure that outlives those attempts surfaces as a per-file fetch error, leaving that file un-reindexed until the next run rather than failing the whole service.

**GitHub Trees truncation** — Very large repositories may have their tree response silently truncated by the GitHub API. The pipeline logs a warning but does not retry or paginate to recover the missing entries.

**Dense-embedding truncation drops the tail of huge symbols** — The embedding text is budgeted to `EMBEDDING_MAX_CHARS` (provider-aware default, configurable). A symbol larger than the budget has its tail excluded from the *dense* vector (BM25 and the stored source keep everything), so semantic search over that tail relies on BM25 alone. Truncation now emits a `WARNING`; the deferred sub-chunking fix is described in the [Embedding Text Construction](#5-embedding-text-construction) section above.
