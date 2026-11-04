---
id: qdrant-collections
title: Qdrant Collections
sidebar_position: 8
---

# Qdrant Collections

semcode stores everything in Qdrant. Collection names are configurable via `QDRANT_COLLECTION` and
`QDRANT_COMMITS_COLLECTION` (see [Configuration](configuration.md#qdrant)).

---

## `code_symbols`

One point per parsed symbol, carrying **two** named vectors:

- `text-dense` — cosine distance, HNSW (`m=16`, `ef_construct=128`), size determined by the embedding provider
  (see [Dense Vectors](dense-vectors.md))
- `text-sparse` — BM25 over code-identifier subword tokens, in-memory sparse index
  (see [Sparse Vectors](sparse-vectors.md))

`search_code` queries both via a Qdrant `query_points` call with `FusionQuery(fusion=RRF)` — see
[Retrieval with RRF](retrieval-rrf.md).

**Indexed payload fields** (`language`, `service`, `symbol_type`, `chunk_tier`, `parent_name`, `file_path`) are
usable as filters. `search_code` and `find_symbol` expose `chunk_tier` (`"method"` or `"class"`) directly, so a
query can be scoped to just classes or just methods.

The full payload also includes `signature`, `docstring`, `annotations`, `package`, `start_line`, `end_line`,
`file_hash`, `indexed_at`, and language-specific extras (`http_method`, `http_route`, `spring_stereotype`,
`lombok_annotations`, `is_async`, `uses_memo`, …). See [Data Model](ingestion.md#data-model) for the full field list.

---

## `git_commits`

Git history indexing is a separate, optional pipeline (`server/indexer/git_history.py`), triggered by the
`index_history` MCP tool or `POST /reindex-history`. It embeds commit messages and changed file paths. Full
unified diffs are stored in the payload and retrievable via the `get_commit` tool. The number of commits per
service is capped by `GIT_HISTORY_MAX_COMMITS` (default 500).

Each commit is one **dense-only** vector (cosine, HNSW `m=16` / `ef_construct=128`) — there is no BM25 vector,
so `search_commits` is pure semantic search.

Payload: `sha`, `service`, `message`, `author_name`, `author_email`, `committed_at`, `indexed_at`, `has_diff`,
`diff_truncated`, and `files` (array of changed files with `filename`, `status`, `additions`, `deletions`,
`patch`). `sha`, `service`, `author_name`, and `has_diff` are indexed payload fields.

---

## `service_registry`

Holds services registered on the fly through `POST /reindex` with an inline `github_repo`. See
[Dynamic Service Registration](configuration.md#dynamic-service-registration).

---

## Resetting

`make qdrant-clean` deletes `code_symbols` and `git_commits`; `make qdrant-dashboard` opens the Qdrant UI. Dropping
the collections is also how you switch to an embedding provider with a different vector size — see
[Startup Validation](configuration.md#startup-validation).
