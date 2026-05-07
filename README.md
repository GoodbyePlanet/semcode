![MCP Server](https://img.shields.io/badge/MCP-Server-blue)
![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-green)
![License MIT](https://img.shields.io/badge/License-MIT-yellow)
[![CI](https://github.com/GoodbyePlanet/semcode/actions/workflows/ci.yml/badge.svg)](https://github.com/GoodbyePlanet/semcode/actions/workflows/ci.yml)

# semcode

An MCP (Model Context Protocol) server that provides semantic code search across microservices codebases.
It indexes code symbols and git history from GitHub repositories and makes them searchable via natural
language queries or symbol name lookups.

## How it works

1. Fetches source files from configured GitHub repositories
2. Parses code symbols (functions, classes, methods, components) using Tree-sitter
3. Generates embeddings via Jina Code V2 (served by HuggingFace TEI)
4. Stores vectors in Qdrant for fast semantic search
5. Optionally indexes commit history into a separate Qdrant collection
6. Exposes search and indexing tools through the MCP protocol (and a small HTTP API)

Indexing is **incremental** — files are skipped when their Git blob SHA matches the last indexed version,
and stale entries for deleted files are cleaned up automatically. Pass `force: true` to re-embed everything.

## Supported languages

Language is detected automatically from file extension or filename — no configuration needed.

Go, Java, Python, TypeScript / JavaScript (React), Rust, C#, C, C++, Ruby, PHP, Kotlin, Scala, Swift, Dart, Bash, SQL, Lua, R, Dockerfile, Docker Compose, Markdown, JSON, HTML, CSS, XML.

Most parsers are framework-aware where it matters — Spring stereotypes and HTTP routes for Java/Kotlin, FastAPI/Pydantic for Python, ASP.NET for C#, Rails for Ruby, Laravel/Symfony for PHP, React/SwiftUI/Flutter widgets, etc. See `server/parser/` for the per-language extraction details.

## Setup

**Prerequisites:** Python 3.12+, Docker, GitHub token

```bash
# Install dependencies
uv sync

# Copy and configure environment
cp .env.example .env

# Copy and configure services
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

```bash
docker-compose up
```

This starts three services with health checks and persistent volumes:

| Service                   | Port                         | Volume                           | Purpose                |
|---------------------------|------------------------------|----------------------------------|------------------------|
| **Qdrant**                | `6333` (HTTP), `6334` (gRPC) | `qdrant_data`                    | Vector DB              |
| **Jina Embeddings** (TEI) | `8087`                       | `embeddings_cache`               | Embedding model server |
| **semcode MCP**           | `8090`                       | mounts `./config.yaml` read-only | MCP + HTTP server      |

The MCP server starts with empty collections — trigger an initial index by calling the `reindex` MCP tool
or `POST /reindex` (see below).

## Connecting AI clients

Once the server is running, point your AI client at `http://localhost:8090/mcp`.

**Claude Code (CLI)**

```bash
claude mcp add --transport http semcode http://localhost:8090/mcp
```

## Indexing

The indexing pipeline is symbol-oriented: each function, class, method, or component becomes its own
chunk with a vector embedding and a rich payload.

- **Discovery** — lists all files in the repo at `github_ref`, applying `root` and `exclude` filters
- **Change detection** — compares the file's Git blob SHA to the last indexed value; unchanged files are skipped
- **Parsing** — Tree-sitter walks the AST and emits `CodeSymbol` objects per language
- **Embedding text** — built from signature, docstring, annotations, parent name, and source (truncated at ~6000 chars)
- **Batching** — symbols are embedded in batches of 32 against the TEI server
- **Upsert** — vectors stored in Qdrant under deterministic UUIDs (per service / file / symbol / line)
- **Cleanup** — entries for files no longer in the repo are deleted

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

| Tool                    | Description                                                                                |
|-------------------------|--------------------------------------------------------------------------------------------|
| `search_code`           | Semantic search by query, with optional filters for language, service, symbol type         |
| `find_symbol`           | Look up a symbol by name (exact or fuzzy)                                                  |
| `find_usages`           | Find code that references a given symbol name (semantic search + textual filter)           |
| `get_code_context`      | Fetch the full source of a file — or a specific symbol within it — directly from GitHub    |
| `reindex`               | Trigger code indexing of one or all services (incremental by default; `force` to re-embed) |
| `index_history`         | Index git commit history; automatically fetches diffs for commits missing them             |
| `search_commits`        | Search git commit history with natural language                                            |
| `get_commit`            | Get full details for a specific commit including changed files and diffs                   |
| `list_indexed_services` | List indexed services with file counts, languages, and last-indexed time                   |
| `index_stats`           | Show Qdrant collection statistics and configured services                                  |

## MCP Prompts

| Prompt             | Arguments | Description                                                                                                                                   |
|--------------------|-----------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| `service_overview` | `service` | Walks the client through producing an architectural overview of a service: HTTP entry points, domain types, and notable framework conventions |

## HTTP API

In addition to the MCP tools, the server exposes two HTTP endpoints for triggering indexing
from CI/CD or external schedulers:

| Endpoint                | Body                                       | Description                                  |
|-------------------------|--------------------------------------------|----------------------------------------------|
| `POST /reindex`         | `{"service": "<name>"?, "force": <bool>?}` | Reindex one or all services — returns NDJSON |
| `POST /reindex-history` | `{"service": "<name>"?, "force": <bool>?}` | Index git commit history — returns NDJSON    |

All bodies are optional — omit `service` to act on all services, omit `force` for incremental indexing.
Both endpoints stream NDJSON progress frames in real time, making them suitable for CI/CD pipelines or
any context where observing indexing progress matters.

## Environment variables

| Variable                    | Default                               | Description                                |
|-----------------------------|---------------------------------------|--------------------------------------------|
| `GITHUB_TOKEN`              | *(required)*                          | GitHub token with repo read access         |
| `QDRANT_URL`                | `http://localhost:6333`               | Qdrant connection URL                      |
| `QDRANT_COLLECTION`         | `code_symbols`                        | Collection name for code symbol vectors    |
| `QDRANT_COMMITS_COLLECTION` | `git_commits`                         | Collection name for commit message vectors |
| `EMBEDDINGS_URL`            | `http://localhost:8087`               | Jina TEI URL                               |
| `EMBEDDINGS_MODEL`          | `jinaai/jina-embeddings-v2-base-code` | Embedding model ID                         |
| `EMBEDDINGS_DIMENSIONS`     | `768`                                 | Vector dimensions                          |
| `GIT_HISTORY_MAX_COMMITS`   | `500`                                 | Max commits indexed per service            |
| `MCP_TRANSPORT`             | `streamable-http`                     | One of `streamable-http`, `sse`, `stdio`   |
| `MCP_HOST` / `MCP_PORT`     | `0.0.0.0` / `8090`                    | Server bind address                        |
| `CONFIG_PATH`               | `./config.yaml`                       | Path to the services config file           |

## Qdrant collections

**`code_symbols`** — one vector per parsed symbol. Indexed payload fields (`language`, `service`,
`symbol_type`, `chunk_tier`, `parent_name`, `file_path`) are usable as filters in `search_code`.
The full payload also includes `signature`, `docstring`, `annotations`, `package`, `start_line`,
`end_line`, `file_hash`, `indexed_at`, and language-specific extras (`http_method`, `http_route`,
`spring_stereotype`, `lombok_annotations`, `is_async`, `uses_memo`, …).

**`git_commits`** — one vector per commit. Payload includes `sha`, `service`, `message`,
`author_name`, `author_email`, `committed_at`, `indexed_at`, `has_diff`, `diff_truncated`,
and `files` (array of changed files with `filename`, `status`, `additions`, `deletions`, `patch`).

Both collections use cosine distance and HNSW indexing (`m=16`, `ef_construct=128`).

## Project structure

```
server/
├── main.py          # MCP server entry point + lifespan
├── config.py        # Settings and service configuration
├── state.py         # Shared store singletons
├── parser/          # Tree-sitter parsers (Go, Java, Python, TypeScript, Rust, C#, C, C++, Ruby, PHP, Kotlin, Scala, Swift, Dart, Bash, SQL, Lua, R, Dockerfile, Compose, Markdown, JSON, HTML, CSS, XML)
├── embeddings/      # Jina Code V2 embedding client (batched, async)
├── indexer/         # GitHub fetcher, code indexing pipeline, git history pipeline
├── store/           # Qdrant vector store (code_symbols and git_commits)
├── tools/           # MCP tool implementations (search, index, history, admin)
├── prompts/         # MCP prompt templates (service_overview)
└── routes/          # HTTP routes (reindex, reindex-history)
```
