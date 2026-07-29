# Configuration

This document covers every configuration knob in semcode: environment variables read from `.env`, the `config.yaml` service definitions, the dynamic service registry (the alternative to `config.yaml`), and the startup validation that fires when the embedding provider and Qdrant collection dimensions conflict.

---

## Overview

semcode is configured through:

- **`.env`** — environment variables for infrastructure settings (embedding provider, Qdrant URL, GitHub token, server port). Loaded by `pydantic-settings` at startup.
- **`config.yaml`** *(optional)* — a static, curated list of service definitions: which GitHub repositories to index, under what names, and with what filters. Loaded on demand by `settings.load_services()`.
- **The dynamic service registry** *(optional, alternative or complement to `config.yaml`)* — services registered on the fly via `POST /reindex`'s `github_repo` field, persisted in a Qdrant collection instead of a file. See [Dynamic Service Registration](#dynamic-service-registration) below.

`config.yaml` is entirely optional — a missing file is treated as zero configured services, not an error. A `config.example.yaml` is provided in the repository root as a starting point if you do want it.

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
| `GITHUB_TOKEN` | `""` | GitHub personal access token (or GitHub App installation token). Required for all indexing operations. Without it, GitHub API calls return 403. A single token is used for every service, whether from `config.yaml` or the dynamic registry — see the note in [Dynamic Service Registration](#dynamic-service-registration). |
| `CONFIG_PATH` | `./config.yaml` | Path to the optional services config file. Relative to the working directory at server start. A missing file means zero `config.yaml`-defined services, not an error. |
| `GIT_HISTORY_MAX_COMMITS` | `500` | Maximum number of commits fetched per service for git history indexing. |
| `CODE_CONTEXT_CACHE_SIZE` | `128` | Number of file contents `get_code_context` keeps cached in memory, keyed on the indexed git blob SHA. Repeated context fetches for the same file are served locally instead of hitting the GitHub API. Set to `0` to disable caching. |
| `CODE_CONTEXT_CACHE_TTL` | `900` | Seconds a cached file content stays valid. Entries are keyed on content (blob SHA), so the TTL only bounds memory for files that fall out of use. |
| `EMBEDDING_MAX_CHARS` | provider-aware — see below | Max characters of a symbol's dense-embedding text (preamble + signature + docstring + source). Oversized symbols are truncated (with a logged `WARNING`). Set this explicitly to override the derived default for any provider. |

Since providers differ hugely in context window (2K–32K tokens), `EMBEDDING_MAX_CHARS` defaults to a value derived from `EMBEDDINGS_PROVIDER`'s default model (~3 chars/token, ~10% safety margin for the preamble). This is a per-provider default, not per-model — if you change `*_MODEL` to a model with a smaller or larger window than the provider's default, set `EMBEDDING_MAX_CHARS` explicitly.

| `EMBEDDINGS_PROVIDER` | Default model | Max input tokens | Derived `EMBEDDING_MAX_CHARS` default |
|---|---|---|---|
| `jina` | `jinaai/jina-embeddings-v2-base-code` | 8,192 | 22,000 |
| `jina-api` | `jina-embeddings-v2-base-code` | 8,192 | 22,000 |
| `voyage` | `voyage-code-3` | 32,000 | 86,000 |
| `openai` | `text-embedding-3-large` | 8,192 | 22,000 |
| `ollama` | `nomic-embed-text` | 2,048 | 5,500 |

Note: self-hosted Jina TEI (`jina`) does not trim oversized inputs server-side and will error past the model's true token limit, so avoid setting `EMBEDDING_MAX_CHARS` far above the default for that provider. `voyage`/`openai`/`jina-api` trim oversized inputs server-side, so headroom there is safer.

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

## Dynamic Service Registration

`config.yaml` doesn't scale to hundreds of repos — every addition means hand-editing one file. As an alternative,
`POST /reindex` accepts the same fields inline in the request body, registering the service on the fly instead of
requiring a `config.yaml` entry:

```jsonc
POST /reindex
{
  "service": "catalog-service",     // required when github_repo is present
  "github_repo": "my-org/my-repo",
  "github_ref": "main",             // optional, defaults to "main"
  "root": "services/catalog",       // optional
  "exclude": ["**/test/**"]         // optional
}
```

This is the mechanism behind the [GitHub Actions example](../examples/github-actions/reindex-on-merge.yml) — a repo
adds that workflow to its own CI, and every merge to `main`/`master` both registers it and triggers indexing, with
no central file to edit.

**Where it's stored**: registrations are persisted in a dedicated Qdrant collection (`service_registry`) via
`ServiceRegistry` (`server/store/service_registry.py`), not a file — this is what makes them survive server
restarts and, unlike `config.yaml`, safe to write to from an unattended, unauthenticated HTTP request without
needing a writable file mount.

**Resolution**: `load_effective_services()` merges `config.yaml` services with everything in the registry every
time services are resolved (on every `index_service`/`index_all` call, and in `get_code_context`) — there's no
in-memory cache, same as `config.yaml`. **`config.yaml` always wins on a name collision** — if a `POST /reindex`
tries to register a name that's already defined in `config.yaml`, the registry entry is stored but ignored when
resolving what to index. This stops a stray or malicious request from silently repointing a curated service to a
different repo.

**Visibility**: registered services appear in `list_indexed_services` (once they have indexed symbols) and in
`index_stats`, under "Registered dynamically via API" — listed separately from `config.yaml`'s "From config.yaml".

**Not covered**: `POST /reindex-history` does not accept these inline fields — it only registers through
`/reindex`. Once a service exists in the registry, `/reindex-history` picks it up automatically (same
`load_effective_services()` call), but nothing registers a service for you if you only ever call the history
endpoint.

**No deregistration**: there's currently no way to remove a registered service short of deleting its point
directly from the `service_registry` Qdrant collection. It will never be auto-pruned — `prune_orphaned_services`
treats every merged service (config.yaml + registry) as known-good.

**No new access control**: `POST /reindex` has no authentication, same as before this feature existed — providing
`github_repo` doesn't gate behind anything new. This means an unauthenticated caller can make the server index and
permanently register any repo `GITHUB_TOKEN` can read, not just repos already known to it. Put the HTTP API behind
your own network boundary or reverse-proxy auth if that's a concern.

**`GITHUB_TOKEN` at scale**: the same single token is used for every repo, `config.yaml` or registry. A
fine-grained PAT scoped to an explicit repo list works for a handful of curated services, but for org-wide
self-registration — where any repo can onboard itself just by adding the workflow — a PAT needs its scope updated
out-of-band every time a new repo starts using it, or that repo's first indexing run fails with a 403. A GitHub
App installed org-wide (`Contents: read`, all repositories) avoids that upkeep.

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

**`load_services()` reads from disk on every call** — there is no in-memory cache for `config.yaml`. Adding, removing, or renaming services takes effect on the next index run without restarting. The downside is a file I/O operation on every indexing request. A missing file returns `[]` (see below); an empty file (`yaml.safe_load` returning `None`) is also treated as zero services.

**API keys are not validated at startup** — unlike dimension validation (which crashes startup), `JINA_API_KEY`, `VOYAGE_API_KEY`, and `OPENAI_API_KEY` are checked only in the provider constructor, which is deferred to first use. A missing key causes a `RuntimeError` on the first embedding request, not at boot. A server configured with a valid Qdrant collection but a missing API key will start successfully and fail only when indexing is first attempted.

**`CONFIG_PATH` is cwd-relative** — the default `./config.yaml` is resolved relative to the working directory at server start, not relative to the binary or the project root. If the server is started from a different directory, the config file will not be found — same effect as not having one: zero `config.yaml`-defined services.

**Docker bind-mount footgun**: if `CONFIG_PATH` resolves to a directory instead of a file, `load_services()` raises a clear `RuntimeError` rather than crashing with a cryptic `IsADirectoryError`. This specifically guards against a Docker bind mount pointing at a host `config.yaml` that doesn't exist — Docker silently creates an empty directory there instead of leaving the path absent. `docker-compose.yaml` avoids this by not mounting `config.yaml` at all by default; use the `-with-config` Makefile targets (which layer `docker-compose.config-yaml.yml` on top) if you want it mounted, rather than hand-editing the volume line.

**`GITHUB_TOKEN` defaults to empty string** — a missing token doesn't prevent server startup; it causes a 403 from the GitHub API on the first indexing request.

**No Qdrant authentication configuration** — only the URL is configurable. There is no way to configure a Qdrant API key, TLS certificates, or authentication headers. Qdrant running with authentication enabled requires code changes.
