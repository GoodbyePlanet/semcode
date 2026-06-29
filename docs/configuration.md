# Configuration

This document covers every configuration knob in semcode: environment variables read from `.env`, the `config.yaml` service definitions, and the startup validation that fires when the embedding provider and Qdrant collection dimensions conflict.

---

## Overview

semcode is configured through two files:

- **`.env`** — environment variables for infrastructure settings (embedding provider, Qdrant URL, GitHub token, server port). Loaded by `pydantic-settings` at startup.
- **`config.yaml`** — service definitions: which GitHub repositories to index, under what names, and with what filters. Loaded on demand by `settings.load_services()`.

A `config.example.yaml` is provided in the repository root as a starting point.

---

## Environment Variables

All variables are optional with the shown defaults, except where marked **required**.

### Embedding Provider

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDINGS_PROVIDER` | `jina` | Dense embedding provider. One of: `jina`, `jina-api`, `voyage`, `openai`, `ollama`. |

Only one provider is active at a time. Changing this variable requires a server restart. If the existing Qdrant collection was created with a different provider's dimension count, a startup error will occur on the next index run (see Startup Validation).

### Jina (self-hosted, default)

Used when `EMBEDDINGS_PROVIDER=jina`. Requires a running [HuggingFace Text Embeddings Inference](https://github.com/huggingface/text-embeddings-inference) server.

| Variable | Default | Description |
|----------|---------|-------------|
| `JINA_URL` | `http://localhost:8087` | TEI server base URL |
| `JINA_MODEL` | `jinaai/jina-embeddings-v2-base-code` | Model name (informational — the TEI server manages the loaded model) |
| `JINA_DIMENSIONS` | `768` | Output vector size. Must match the model loaded in TEI. |

### Jina API (hosted)

Used when `EMBEDDINGS_PROVIDER=jina-api`.

| Variable | Default | Description |
|----------|---------|-------------|
| `JINA_API_KEY` | — | **Required.** Jina AI API key. |
| `JINA_API_MODEL` | `jina-embeddings-v2-base-code` | Model name. Known models: `jina-embeddings-v2-base-code` (768), `jina-code-embeddings-0.5b` (896), `jina-code-embeddings-1.5b` (1536). |
| `JINA_API_DIMENSIONS` | `None` | Optional Matryoshka truncation. When set, the API shrinks vectors to this size. |

### Voyage AI

Used when `EMBEDDINGS_PROVIDER=voyage`.

| Variable | Default | Description |
|----------|---------|-------------|
| `VOYAGE_API_KEY` | — | **Required.** Voyage AI API key. |
| `VOYAGE_MODEL` | `voyage-code-3` | Model name. Known models and native dims: `voyage-code-3` (1024), `voyage-3` (1024), `voyage-3-large` (1024), `voyage-3-lite` (512), `voyage-large-2` (1536), `voyage-code-2` (1536). |
| `VOYAGE_DIMENSIONS` | `None` | Optional output dimension override (Matryoshka). |

### OpenAI

Used when `EMBEDDINGS_PROVIDER=openai`.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | **Required.** OpenAI API key. |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-large` | Model name. Known models and native dims: `text-embedding-3-large` (3072), `text-embedding-3-small` (1536), `text-embedding-ada-002` (1536). |
| `OPENAI_DIMENSIONS` | `None` | Optional Matryoshka truncation. |

### Ollama (self-hosted)

Used when `EMBEDDINGS_PROVIDER=ollama`. Requires a running [Ollama](https://ollama.com) instance with the target model pulled.

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server base URL |
| `OLLAMA_MODEL` | `nomic-embed-text` | Model name. Known models and dims: `nomic-embed-text` (768), `mxbai-embed-large` (1024), `all-minilm` (384), `snowflake-arctic-embed` (1024), `bge-m3` (1024). |
| `OLLAMA_DIMENSIONS` | `None` | Required for unknown models — set to the model's output dimension. |

### Qdrant

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_URL` | `http://localhost:6333` | Qdrant server URL |
| `QDRANT_COLLECTION` | `code_symbols` | Collection name for code symbol vectors |
| `QDRANT_COMMITS_COLLECTION` | `git_commits` | Collection name for git commit history vectors |

### MCP Server

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `streamable-http` | Transport protocol. One of: `streamable-http`, `sse`, `stdio`. |
| `MCP_HOST` | `127.0.0.1` | Bind address |
| `MCP_PORT` | `8090` | Listen port |

### General

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_TOKEN` | `""` | GitHub personal access token. Required for all indexing operations. Without it, GitHub API calls return 403. |
| `CONFIG_PATH` | `./config.yaml` | Path to the services config file. Relative to the working directory at server start. |
| `GIT_HISTORY_MAX_COMMITS` | `500` | Maximum number of commits fetched per service for git history indexing. |
| `EMBEDDING_MAX_CHARS` | `6000` | Max characters of a symbol's dense-embedding text (preamble + signature + docstring + source). Oversized symbols are truncated (with a logged `WARNING`). Keep conservative for self-hosted Jina TEI, which errors on inputs over the model's token limit; raise it (e.g. `~24000`) for `voyage`/`openai`/`jina-api`, which trim oversized inputs server-side and accept ~8k–32k tokens. ~3–4 chars ≈ 1 token for code. |

---

## config.yaml Structure

`config.yaml` defines the services (repositories) to index. It is read fresh on every indexing request — changes take effect on the next index run without a server restart.

```yaml
services:
  - name: catalog-service          # required — used as path prefix in Qdrant
    github_repo: my-org/my-repo    # required — GitHub repo in "org/repo" format
    github_ref: main               # optional — branch, tag, or commit SHA (default: "main")
    root: services/catalog         # optional — only index files under this path prefix
    exclude:                       # optional — glob patterns to skip
      - "**/test/**"
      - "**/target/**"
      - "**/*.generated.java"
```

### Field Notes

**`name`** — becomes the service prefix in all stored file paths (`{name}/{path_in_repo}`) and in Qdrant payload `service` field. Must be unique across services.

**`github_ref`** — can be a branch name, tag, or full commit SHA. Using a commit SHA pins the index to a specific snapshot.

**`root`** — useful for monorepos. Only files under `root/` are indexed; the `root/` prefix is stripped from stored paths.

**`exclude`** — fnmatch glob patterns matched against both the full file path and the basename. Common patterns: `**/test/**`, `**/target/**`, `**/build/**`, `**/*.generated.*`.

---

## Startup Validation

`QdrantStore.ensure_collection()` runs in the server's **lifespan context** (`server/main.py:39`) — at boot, before any requests are served. If the Qdrant collection already exists, its vector dimension is compared against the configured provider's `dimensions` value. A mismatch raises:

```
RuntimeError: Qdrant collection 'code_symbols' was created with vector size 768,
but the configured embedding provider produces vectors of size 1024. Either revert
EMBEDDINGS_PROVIDER to the original setting, or drop the collection (this deletes
the existing index) and reindex.
```

This error aborts server startup — the server will not accept connections until the mismatch is resolved.

**To switch embedding providers on an existing index:**
1. Stop the server
2. Drop the Qdrant collection (via Qdrant dashboard or API)
3. Update `EMBEDDINGS_PROVIDER` (and related vars) in `.env`
4. Start the server — `ensure_collection()` will recreate the collection with the new dimensions
5. Trigger a full reindex

---

## Observations

**`load_services()` reads from disk on every call** — there is no in-memory cache for `config.yaml`. Adding, removing, or renaming services takes effect on the next index run without restarting. The downside is a file I/O operation on every indexing request.

**API keys are not validated at startup** — unlike dimension validation (which crashes startup), `JINA_API_KEY`, `VOYAGE_API_KEY`, and `OPENAI_API_KEY` are checked only in the provider constructor, which is deferred to first use. A missing key causes a `RuntimeError` on the first embedding request, not at boot. A server configured with a valid Qdrant collection but a missing API key will start successfully and fail only when indexing is first attempted.

**`CONFIG_PATH` is cwd-relative** — the default `./config.yaml` is resolved relative to the working directory at server start, not relative to the binary or the project root. If the server is started from a different directory, the config file will not be found.

**`GITHUB_TOKEN` defaults to empty string** — a missing token doesn't prevent server startup; it causes a 403 from the GitHub API on the first indexing request.

**No Qdrant authentication configuration** — only the URL is configurable. There is no way to configure a Qdrant API key, TLS certificates, or authentication headers. Qdrant running with authentication enabled requires code changes.
