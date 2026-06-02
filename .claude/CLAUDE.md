# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**semcode** is an MCP (Model Context Protocol) server that provides hybrid semantic code search over GitHub
repositories. It lets AI clients search codebases using natural language or symbol names by combining dense vector
embeddings with BM25 sparse search and Tree-sitter-based code parsing.

## Commands

```bash
# Install dependencies
uv sync                   # production deps
uv sync --group dev       # include test/dev deps

# Run tests
uv run pytest                          # all tests
uv run pytest tests/parser/            # parser tests only
uv run pytest tests/test_pipeline.py   # single test file

# Docker (Qdrant + optional local Jina TEI)
make docker-up            # hosted embeddings provider
make docker-up-jina       # local Jina TEI embeddings
make docker-logs          # all container logs
make docker-logs-semcode  # semcode container only

# Trigger indexing
make index-code           # POST /reindex
make index-history        # POST /reindex-history

# Qdrant utilities
make qdrant-clean         # delete all collections
make qdrant-dashboard     # open Qdrant UI
```

## Architecture

All server code lives under `server/`. The system has two main phases: **ingestion** and **retrieval**.

### Ingestion pipeline (`server/indexer/`)

1. **Discovery** — `github_source.py` lists files in a GitHub repo and applies filters from config
2. **Change detection** — compares Git blob SHAs to skip unchanged files
3. **Parsing** — `parser/registry.py` routes each file to the correct language parser; each parser uses Tree-sitter to
   extract `CodeSymbol` objects (functions, classes, methods, etc.) with framework metadata
4. **Embedding** — `embeddings/factory.py` creates two vectors per symbol: dense (Jina/Voyage/OpenAI/Ollama) + BM25
   sparse (`embeddings/bm25.py` with camelCase/snake_case tokenization)
5. **Upsert** — both vectors stored in Qdrant collection `code_symbols` with rich payload (language, type, file, line,
   signature, docstring, annotations, parent class, framework metadata)
6. **Cleanup** — removes stale entries for deleted files/symbols
7. **Git history** (optional) — `git_history.py` indexes commits into a separate `git_commits` collection (dense-only)

### Retrieval (`server/store/`, `server/tools/`)

- `store/qdrant.py` runs hybrid search via Qdrant `FusionQuery(fusion=RRF)` — combines dense and BM25 sparse results
  using Reciprocal Rank Fusion
- `store/commit_store.py` handles commit search (dense-only)
- `tools/` contains the MCP tool implementations: `search.py`, `index.py`, `history.py`, `admin.py`

### MCP interface (`server/main.py`)

FastMCP serves tools and prompts over stdio, SSE, or HTTP. HTTP indexing endpoints (`POST /reindex`,
`POST /reindex-history`) return streaming NDJSON for CI/CD consumption.

### Configuration

`server/config.py` loads `config.yaml` via Pydantic. Services (repos to index), embedding provider, and Qdrant
connection are all defined there.

### Parser structure (`server/parser/`)

One file per language (24 languages). Each implements the abstract `CodeParser` from `base.py` and returns a list of
`CodeSymbol` dataclasses. When adding a new language: implement the parser, register it in `registry.py`, add fixture
files under `tests/fixtures/<language>/`, and add snapshot tests under `tests/parser/`.

### Embedding providers (`server/embeddings/`)

Pluggable via `factory.py` registry. Swap providers in config without reindexing. BM25 sparse vectors are always
generated alongside dense vectors.

### Test structure

```
tests/
├── parser/               # snapshot tests per language (24 files)
├── fixtures/             # canonical code samples for parser tests
├── embeddings/           # embedding provider tests
├── test_pipeline.py      # indexing pipeline integration
├── test_store.py         # Qdrant store operations
├── test_reindex_route.py # HTTP endpoint tests
└── conftest.py           # shared fixtures
```

Async tests use `asyncio_mode = "auto"` (pytest-asyncio). HTTP calls are mocked with `respx`.
