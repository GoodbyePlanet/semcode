![MCP Server](https://img.shields.io/badge/MCP-Server-blue)
![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-green)
![License MIT](https://img.shields.io/badge/License-MIT-yellow)
[![CI](https://github.com/GoodbyePlanet/semcode/actions/workflows/ci.yml/badge.svg)](https://github.com/GoodbyePlanet/semcode/actions/workflows/ci.yml)

# semcode

An MCP (Model Context Protocol) server providing hybrid semantic search over code across a set of
GitHub repositories that you list in `config.yaml`. It parses symbols
with *Tree-sitter* and indexes both code and git commit history, so AI clients can query them by
natural language or by symbol name.

Hybrid retrieval combines dense embeddings with BM25, so both natural-language queries
("where do we publish order events?") and symbol-name lookups (`PlaceOrderRequest`) work well.

## How it works

1. Fetches source files from configured GitHub repositories
2. Parses code symbols (functions, classes, methods, components) using Tree-sitter
3. Generates **two** embeddings per symbol — a dense semantic vector (pluggable provider: Jina Code V2 by default, or
   Voyage / OpenAI / Ollama) and a BM25 sparse vector keyed on code-identifier tokens (camelCase / snake_case split into
   subwords)
4. Stores both in Qdrant and retrieves them with **hybrid search** — Reciprocal Rank Fusion (RRF) over the dense and
   sparse results — so natural-language queries and symbol-name lookups both work well
5. Optionally indexes commit history into a separate Qdrant collection (dense-only)
6. Exposes search and indexing tools through the MCP protocol (and a small HTTP API)

Indexing is **incremental** — files are skipped when their Git blob SHA matches the last indexed version.
Files that no longer exist (or parse to zero symbols) are cleaned up automatically. Pass `force: true`
to re-embed everything.

## Supported languages

Language is detected automatically from file extension or filename — no configuration needed.

Go, Java, Python, TypeScript / JavaScript (React), Rust, C#, C, C++, Ruby, PHP, Kotlin, Scala, Swift, Dart, Bash, SQL,
Lua, R, Dockerfile, Docker Compose, Markdown, JSON, HTML, CSS, XML.

Most parsers are framework-aware where it matters — Spring stereotypes and HTTP routes for Java/Kotlin, FastAPI/Pydantic
for Python, ASP.NET for C#, Rails for Ruby, Laravel/Symfony for PHP, React/SwiftUI/Flutter widgets, etc. See
`server/parser/` for the per-language extraction details.

## Setup

**Prerequisites:** Python 3.12+, Docker, GitHub token

```bash
# Install dependencies
uv sync

# Copy environment file, then edit .env to set GITHUB_TOKEN
# (a fine-grained PAT with Contents: read on the target repos is sufficient)
cp .env.example .env

# Copy services config, then list the repositories you want indexed
cp config.example.yaml config.yaml
```

Configure which repositories to index in `config.yaml`:

```yaml
services:
  - name: my-service
    github_repo: owner/repo
    github_ref: main              # optional, defaults to "main" — branch, tag, or commit SHA
    root: src/main/java           # optional — limit indexing to this subdirectory (useful for monorepos)
    exclude: # optional — skip matching paths
      - "**/vendor/**"
      - "**/node_modules/**"
```

The indexer automatically discovers and indexes all files with recognised extensions. Use `root` to scope a service to a
subdirectory within a shared repo, and `exclude` to skip paths you don't want indexed (tests, build artifacts, generated
code, etc.).

## Running

There are two ways to run, depending on whether you want embeddings to come from a local
container or a hosted provider. Pick one:

**Path A — local Jina via TEI (default, no API key required):**

```bash
make docker-up-jina
# or: docker-compose --profile jina up
```

**Path B — hosted provider (Voyage / OpenAI) or local Ollama:**

```bash
# 1. In .env, set EMBEDDINGS_PROVIDER=voyage|openai|ollama and the relevant API key.
# 2. Then start without the jina profile:
make docker-up
# or: docker-compose up
```

> ⚠ The default `EMBEDDINGS_PROVIDER` is `jina`. If you start without `--profile jina` but leave
> the provider on the default, semcode will boot (Jina is `required: false` in compose) but the
> first embedding call will fail with a connection error — there's no auto-fallback.

Services started with health checks and persistent volumes:

| Service                   | Profile | Port                         | Volume                           | Purpose                |
|---------------------------|---------|------------------------------|----------------------------------|------------------------|
| **Qdrant**                | always  | `6333` (HTTP), `6334` (gRPC) | `qdrant_data`                    | Vector DB              |
| **Jina Embeddings** (TEI) | `jina`  | `8087`                       | `embeddings_cache`               | Embedding model server |
| **semcode MCP**           | always  | `8090`                       | mounts `./config.yaml` read-only | MCP + HTTP server      |

The MCP server starts with empty collections — trigger an initial index by calling the `reindex` MCP tool
or `POST /reindex` (see below).

## Connecting AI clients

Once the server is running, point your AI client at `http://localhost:8090/mcp`.

**Claude Code (CLI)**

```bash
claude mcp add --transport http semcode http://localhost:8090/mcp
```

**Other MCP clients (Claude Desktop, Cursor, etc.)** — add an entry to the client's MCP config:

```json
{
  "mcpServers": {
    "semcode": {
      "transport": "http",
      "url": "http://localhost:8090/mcp"
    }
  }
}
```

## Indexing

The indexing pipeline is symbol-oriented: each function, class, method, or component becomes its own
chunk with a vector embedding and a rich payload.

- **Discovery** — lists all files in the repo at `github_ref`, applying `root` and `exclude` filters
- **Change detection** — compares the file's Git blob SHA to the last indexed value; unchanged files are skipped
- **Parsing** — Tree-sitter walks the AST and emits `CodeSymbol` objects per language
- **Dense embedding text** — language label, symbol kind, parent class, package, framework extras (Spring stereotype,
  HTTP route, Lombok, React memo), docstring, signature, and source (source truncated at ~6000 chars)
- **Sparse (BM25) embedding text** — signature, docstring, and source. Code identifiers are split into subwords (
  camelCase, snake_case) before tokenization, so `getUserById` indexes as `get`, `user`, `by`, `id` as well as the full
  token
- **Batching** — dense provider batches at 32 (Jina/TEI, Ollama) or 128 (Voyage, OpenAI); BM25 runs in-process
- **Upsert** — both vectors stored under one point in Qdrant, keyed by a deterministic UUID (per service / file /
  symbol / line)
- **Cleanup** — entries for files no longer in the repo (or that now parse to zero symbols) are deleted

Git history indexing is a separate, optional pipeline that embeds commit messages and changed file
paths into the `git_commits` collection. Full unified diffs are stored in the payload and retrievable
via the `get_commit` tool. The number of commits per service is capped by `GIT_HISTORY_MAX_COMMITS`
(default 500).

## Tests

```bash
uv sync --group dev
uv run pytest
```

Tests live under `tests/`:

- `tests/parser/test_*.py` — one file per language; snapshots parser behavior against canonical fixtures in
  `tests/fixtures/<language>/`
- `tests/test_pipeline.py`, `tests/test_store.py`, `tests/test_git_history.py` — integration tests for the indexing
  pipeline and Qdrant store
- `tests/test_reindex_route.py` — HTTP route tests

## MCP Tools

| Tool                    | Description                                                                                          |
|-------------------------|------------------------------------------------------------------------------------------------------|
| `search_code`           | Hybrid (dense + BM25) search by query, with optional filters for language, service, symbol type      |
| `find_symbol`           | Look up a symbol by name — exact match, or case-insensitive substring when `exact=false`             |
| `find_usages`           | Find code that references a given symbol name (semantic search, then excludes the definition itself) |
| `get_code_context`      | Fetch the full source of a file — or a specific symbol within it — directly from GitHub              |
| `reindex`               | Trigger code indexing of one or all services (incremental by default; `force` to re-embed)           |
| `index_history`         | Index git commit history; automatically fetches diffs for commits missing them                       |
| `search_commits`        | Search git commit history with natural language                                                      |
| `get_commit`            | Get full details for a specific commit including changed files and diffs                             |
| `list_indexed_services` | List indexed services with chunk and file counts, languages, and last-indexed time                   |
| `index_stats`           | Show Qdrant collection statistics and configured services                                            |

## MCP Prompts

| Prompt                   | Arguments | Description                                                                                                                                                                                 |
|--------------------------|-----------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `service_overview`       | `service` | Walks the client through producing an architectural overview of a service: HTTP entry points, domain types, and notable framework conventions                                               |
| `system_design_overview` | *(none)*  | Walks the client through producing a complete system design overview: service inventory, communication topology, shared data stores, and cross-cutting concerns — includes Mermaid diagrams |

## HTTP API

In addition to the MCP tools, the server exposes two HTTP endpoints for triggering indexing
from CI/CD or external schedulers:

| Endpoint                | Body                                       | Description                                  |
|-------------------------|--------------------------------------------|----------------------------------------------|
| `POST /reindex`         | `{"service": "<name>"?, "force": <bool>?}` | Reindex one or all services — returns NDJSON |
| `POST /reindex-history` | `{"service": "<name>"?, "force": <bool>?}` | Index git commit history — returns NDJSON    |

All bodies are optional — omit `service` to act on all services, omit `force` for incremental indexing.
Both endpoints stream **newline-delimited JSON** (one frame per line) so you can consume progress
in real time from CI/CD pipelines or any other client.

Frame shapes:

```jsonc
// in-flight progress
{"type": "progress", "phase": "discovery|upserting|cleanup", "current": 12, "total": 200, "percentage": 6.0, "service": "my-service"}
// final summary (one per request)
{"type": "done", "result": {"files": 42, "chunks": 318, "skipped": 5}}
// emitted instead of "done" on failure
{"type": "error", "message": "..."}
```

For `/reindex-history` the `phase` value is `discovery|embedding|upserting` and the `done` result is
`{"new": int, "skipped": int, "diff_updated": int}`.

## Environment variables

| Variable                    | Default                 | Description                                                                   |
|-----------------------------|-------------------------|-------------------------------------------------------------------------------|
| `GITHUB_TOKEN`              | *(required)*            | GitHub token with repo read access                                            |
| `QDRANT_URL`                | `http://localhost:6333` | Qdrant connection URL                                                         |
| `QDRANT_COLLECTION`         | `code_symbols`          | Collection name for code symbol vectors                                       |
| `QDRANT_COMMITS_COLLECTION` | `git_commits`           | Collection name for commit message vectors                                    |
| `EMBEDDINGS_PROVIDER`       | `jina`                  | One of `jina`, `jina-api`, `voyage`, `openai`, `ollama` — see *Embedding providers* below |
| `GIT_HISTORY_MAX_COMMITS`   | `500`                   | Max commits indexed per service                                               |
| `MCP_TRANSPORT`             | `streamable-http`       | One of `streamable-http`, `sse`, `stdio`                                      |
| `MCP_HOST` / `MCP_PORT`     | `127.0.0.1` / `8090`    | Server bind address                                                           |
| `CONFIG_PATH`               | `./config.yaml`         | Path to the services config file                                              |

## Embedding providers

The embedding backend is selectable via `EMBEDDINGS_PROVIDER`. Default is `jina` so existing
deployments keep working unchanged. Each provider derives its own vector dimensions from the
configured model — no need to set dimensions manually unless you want to override.

| Variable                 | Default                               | Applies to | Description                                                                                                                     |
|--------------------------|---------------------------------------|------------|---------------------------------------------------------------------------------------------------------------------------------|
| `JINA_URL`               | `http://localhost:8087`               | `jina`     | TEI base URL                                                                                                                    |
| `JINA_MODEL`             | `jinaai/jina-embeddings-v2-base-code` | `jina`     | Informational only — the TEI container's `--model-id` flag is what actually loads. Edit `docker-compose.yaml` to change models. |
| `JINA_DIMENSIONS`        | `768`                                 | `jina`     | Vector dimensions of the TEI model                                                                                              |
| `JINA_API_KEY`           | *(required if provider=jina-api)*     | `jina-api` | Jina AI API key (hosted endpoint at `api.jina.ai`)                                                                              |
| `JINA_API_MODEL`         | `jina-embeddings-v2-base-code`        | `jina-api` | Hosted Jina model — also supports `jina-embeddings-v3`, `jina-code-embeddings-0.5b`, `jina-code-embeddings-1.5b`                 |
| `JINA_API_DIMENSIONS`    | *(native)*                            | `jina-api` | Optional Matryoshka override (v3 and code-embeddings models support shrinking); required for models without a native default    |
| `VOYAGE_API_KEY`         | *(required if provider=voyage)*       | `voyage`   | Voyage AI API key                                                                                                               |
| `VOYAGE_MODEL`           | `voyage-code-3`                       | `voyage`   | Voyage embedding model                                                                                                          |
| `VOYAGE_DIMENSIONS`      | *(native)*                            | `voyage`   | Optional override — Voyage code-3 supports `256` / `512` / `1024` / `2048`                                                      |
| `OPENAI_API_KEY`         | *(required if provider=openai)*       | `openai`   | OpenAI API key                                                                                                                  |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-large`              | `openai`   | OpenAI embedding model                                                                                                          |
| `OPENAI_DIMENSIONS`      | *(native)*                            | `openai`   | Optional override (text-embedding-3-* models support shrinking)                                                                 |
| `OLLAMA_URL`             | `http://localhost:11434`              | `ollama`   | Ollama base URL                                                                                                                 |
| `OLLAMA_MODEL`           | `nomic-embed-text`                    | `ollama`   | Ollama embedding model                                                                                                          |
| `OLLAMA_DIMENSIONS`      | *(native)*                            | `ollama`   | Required if using a model not in the built-in dimensions table                                                                  |

`voyage-code-3` outperforms `jinaai/jina-embeddings-v2-base-code` on most code retrieval benchmarks,
so switching to Voyage is also a quality lever, not just a flexibility one.

**Switching providers against an existing index:** if the new provider's vector size differs from
the existing Qdrant collection, the server fails fast at startup with a clear error pointing at the
offending collection. To switch, drop both collections (`code_symbols` and `git_commits`) via the
Qdrant UI or API, then reindex. There is no automatic migration.

**Hosted-only setup (no local TEI container):** set `EMBEDDINGS_PROVIDER` and the relevant API key
in `.env`, then start without the `jina` profile (`docker-compose up` / `make docker-up`). The
`jina-embeddings` container will not start.

## Qdrant collections

**`code_symbols`** — one point per parsed symbol, carrying **two** named vectors:

- `text-dense` — cosine distance, HNSW (`m=16`, `ef_construct=128`), size determined by the embedding provider
- `text-sparse` — BM25 over code-identifier subword tokens, in-memory sparse index

`search_code` queries both via a Qdrant `query_points` call with `FusionQuery(fusion=RRF)`. Indexed
payload fields (`language`, `service`, `symbol_type`, `chunk_tier`, `parent_name`, `file_path`) are
usable as filters. The full payload also includes `signature`, `docstring`, `annotations`, `package`,
`start_line`, `end_line`, `file_hash`, `indexed_at`, and language-specific extras (`http_method`,
`http_route`, `spring_stereotype`, `lombok_annotations`, `is_async`, `uses_memo`, …).

**`git_commits`** — one **dense-only** vector per commit (cosine, HNSW `m=16` / `ef_construct=128`).
Payload includes `sha`, `service`, `message`, `author_name`, `author_email`, `committed_at`,
`indexed_at`, `has_diff`, `diff_truncated`, and `files` (array of changed files with `filename`,
`status`, `additions`, `deletions`, `patch`). `sha`, `service`, `author_name`, and `has_diff` are
indexed payload fields.

## Project structure

```
server/
├── main.py          # MCP server entry point + lifespan
├── config.py        # Settings and service configuration
├── state.py         # Shared store singletons
├── parser/          # Tree-sitter parsers (Go, Java, Python, TypeScript, Rust, C#, C, C++, Ruby, PHP, Kotlin, Scala, Swift, Dart, Bash, SQL, Lua, R, Dockerfile, Compose, Markdown, JSON, HTML, CSS, XML)
├── embeddings/      # Pluggable dense providers (Jina/Voyage/OpenAI/Ollama) + BM25 sparse + code identifier tokenizer
├── indexer/         # GitHub fetcher, code indexing pipeline, git history pipeline
├── store/           # Qdrant vector stores (code_symbols hybrid + git_commits dense)
├── tools/           # MCP tool implementations (search, index, history, admin)
├── prompts/         # MCP prompt templates (service_overview, system_design_overview)
└── routes/          # HTTP routes (reindex, reindex-history)
```
