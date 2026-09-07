# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries from `1.2.0` onward are generated automatically by
[release-please](https://github.com/googleapis/release-please) from Conventional Commit messages on `main`.
The `0.1.0` – `1.1.0` entries below were reconstructed by hand from Git history, because the project had no
tags, releases, or changelog before `1.1.0`.

## [1.2.1](https://github.com/GoodbyePlanet/semcode/compare/v1.2.0...v1.2.1) (2026-09-07)


### Bug Fixes

* drop package-name so merged release PRs get tagged ([878a63e](https://github.com/GoodbyePlanet/semcode/commit/878a63e710644ce52502caa9eecd8bd10e4b128f))
* drop package-name so merged release PRs get tagged ([1ec9013](https://github.com/GoodbyePlanet/semcode/commit/1ec90133a9084573883b0d62d615ad5e2c719017))

## [1.2.0](https://github.com/GoodbyePlanet/semcode/compare/v1.1.0...v1.2.0) (2026-09-07)


### Features

* add automated versioning and release process ([d4d56f1](https://github.com/GoodbyePlanet/semcode/commit/d4d56f1d5e2de3ed1119626f555250b61304dfbc))
* add automated versioning and release process ([8040613](https://github.com/GoodbyePlanet/semcode/commit/8040613a3f8944a6317894f8599ef28d9832bb8b)), closes [#111](https://github.com/GoodbyePlanet/semcode/issues/111)


### Dependencies

* Bump googleapis/release-please-action from 4 to 5 ([a8e1232](https://github.com/GoodbyePlanet/semcode/commit/a8e12321d62ec30fe17e180e6b467c4dc441456e))

## [1.1.0](https://github.com/GoodbyePlanet/semcode/compare/v1.0.0...v1.1.0) (2026-09-07)

The version number `1.1.0` was set in `pyproject.toml` on 2026-08-11 but never tagged. This entry covers
everything that landed between the `1.0.0` version bump (2026-05-06) and the first tagged release.

### ⚠ Notable changes

* **MCP 2.0 migration.** The server moved from FastMCP to `MCPServer` (`mcp >= 2.0.0`). Clients pinned to
  an `mcp` 1.x runtime need to upgrade.
* Embedding providers became pluggable and configurable, so the provider is now a deployment decision
  rather than a hardcoded one.

### Features

* migrate from FastMCP to `MCPServer` (mcp 2.0) ([310cff4](https://github.com/GoodbyePlanet/semcode/commit/310cff4))
* report `serverInfo.version` from package metadata, making `pyproject.toml` the single source of truth
  ([021de2b](https://github.com/GoodbyePlanet/semcode/commit/021de2b))
* add pluggable embedding providers — Jina, Voyage, OpenAI, Ollama ([02c39cd](https://github.com/GoodbyePlanet/semcode/commit/02c39cd))
* add Jina hosted API as an embedding provider ([33253e2](https://github.com/GoodbyePlanet/semcode/commit/33253e2)),
  narrowed to the `v2-base-code` and `code-embeddings` families ([206dd5e](https://github.com/GoodbyePlanet/semcode/commit/206dd5e))
* add 10/20/30/40s backoff on HTTP 429 for the Voyage and OpenAI providers ([8045fa9](https://github.com/GoodbyePlanet/semcode/commit/8045fa9))
* refactor the provider factory to be open for extension ([cd778ee](https://github.com/GoodbyePlanet/semcode/commit/cd778ee))
* add dynamic service registration and a GitHub Actions reindex example ([66d0727](https://github.com/GoodbyePlanet/semcode/commit/66d0727))
* expose `chunk_tier` as a search filter ([6532806](https://github.com/GoodbyePlanet/semcode/commit/6532806))
* **config:** derive the `EMBEDDING_MAX_CHARS` default from the provider context window ([9fec276](https://github.com/GoodbyePlanet/semcode/commit/9fec276))
* add architectural layer detection and business domain mapping to the architecture prompts ([eefd282](https://github.com/GoodbyePlanet/semcode/commit/eefd282))
* add a `system_design_overview` prompt ([d7b142b](https://github.com/GoodbyePlanet/semcode/commit/d7b142b))
* add parser support for the most popular languages ([acfe8a6](https://github.com/GoodbyePlanet/semcode/commit/acfe8a6))
* filter on service name only when searching code ([5a4f6e5](https://github.com/GoodbyePlanet/semcode/commit/5a4f6e5))

### Bug Fixes

* paginate GitHub trees on truncation, instead of silently dropping files ([85a43d0](https://github.com/GoodbyePlanet/semcode/commit/85a43d0))
* make dense-embedding truncation observable and configurable ([6d49e3f](https://github.com/GoodbyePlanet/semcode/commit/6d49e3f))
* preserve index entries when a parser fails, instead of purging them ([243bc61](https://github.com/GoodbyePlanet/semcode/commit/243bc61))
* upsert before deleting stale points, and take a per-service reindex lock ([2cdf49c](https://github.com/GoodbyePlanet/semcode/commit/2cdf49c))
* prune orphaned service data when a service is renamed in `config.yaml` ([b1c998d](https://github.com/GoodbyePlanet/semcode/commit/b1c998d)),
  and guard `prune_orphaned_services` against an empty config ([a1804a9](https://github.com/GoodbyePlanet/semcode/commit/a1804a9))
* validate `config.yaml` services with Pydantic and cache the parsed result ([c0304c2](https://github.com/GoodbyePlanet/semcode/commit/c0304c2))
* include annotations, HTTP route, package, and name in the BM25 text ([9675786](https://github.com/GoodbyePlanet/semcode/commit/9675786))
* close a recall gap and correct the mid-token and migration docs ([f781a77](https://github.com/GoodbyePlanet/semcode/commit/f781a77))
* over-fetch in `find_usages` so definition filtering doesn't shrink results ([d72ac7e](https://github.com/GoodbyePlanet/semcode/commit/d72ac7e))
* report unknown services by what the server can actually see ([25daa5b](https://github.com/GoodbyePlanet/semcode/commit/25daa5b))
* drive the Starlette lifespan ourselves for the SSE transport too ([b023f25](https://github.com/GoodbyePlanet/semcode/commit/b023f25))
* open the DB connection on server startup, not only on MCP client connect ([d591fbb](https://github.com/GoodbyePlanet/semcode/commit/d591fbb))
* pass raw bytes to the Dart and R parsers instead of a decoded `str` ([30c11ab](https://github.com/GoodbyePlanet/semcode/commit/30c11ab))
* fix the Dart and R parsers for tree-sitter language pack 1.9 ([724d01a](https://github.com/GoodbyePlanet/semcode/commit/724d01a))
* fix Docker and CI build hygiene issues ([2c608a2](https://github.com/GoodbyePlanet/semcode/commit/2c608a2))
* fix Jina embeddings request handling ([823a3fe](https://github.com/GoodbyePlanet/semcode/commit/823a3fe))
* minor style and consistency cleanups ([fc9ac10](https://github.com/GoodbyePlanet/semcode/commit/fc9ac10))

### Performance Improvements

* serve partial symbol lookup from a Qdrant full-text index ([6aa8472](https://github.com/GoodbyePlanet/semcode/commit/6aa8472))
* cache `get_code_context` file fetches by Git blob SHA ([9d06217](https://github.com/GoodbyePlanet/semcode/commit/9d06217))

### Code Refactoring

* rename `server/tools/admin.py` to `stats.py` ([86d36ce](https://github.com/GoodbyePlanet/semcode/commit/86d36ce))
* remove progress callbacks from the MCP tools, keeping them on the HTTP routes only ([348bea0](https://github.com/GoodbyePlanet/semcode/commit/348bea0))

### Documentation

* document the RAG ingestion, retrieval, and configuration model ([e1b5862](https://github.com/GoodbyePlanet/semcode/commit/e1b5862))
* add the blog series covering indexing flow, Qdrant payloads, and RRF
  ([ae88a4b](https://github.com/GoodbyePlanet/semcode/commit/ae88a4b), [dd45324](https://github.com/GoodbyePlanet/semcode/commit/dd45324), [c71482f](https://github.com/GoodbyePlanet/semcode/commit/c71482f))
* add a beginner-friendly RAG + semcode presentation ([31736b0](https://github.com/GoodbyePlanet/semcode/commit/31736b0))
* add `CLAUDE.md` for Claude Code guidance ([883d546](https://github.com/GoodbyePlanet/semcode/commit/883d546))

### Tests

* add coverage for `server/tools/*` and the `index_service` pipeline flow ([37e0dfa](https://github.com/GoodbyePlanet/semcode/commit/37e0dfa))

### Dependencies

* weekly grouped Dependabot updates across the `uv` and `github-actions` ecosystems
* hold back `tree-sitter-language-pack` 1.9.0 pending parser fixes ([84b4c77](https://github.com/GoodbyePlanet/semcode/commit/84b4c77))
* bump `cachetools`, `tree-sitter-language-pack`, `pydantic-settings`, `actions/checkout` (4 → 7),
  and `astral-sh/setup-uv` (v7)

### Continuous Integration

* add GitHub Actions CI, Dependabot, and a build badge ([77740da](https://github.com/GoodbyePlanet/semcode/commit/77740da))
* fix ruff lint and formatting across the repo ([e27699c](https://github.com/GoodbyePlanet/semcode/commit/e27699c)),
  and suppress `BLE001` for intentional broad-exception catches ([05cf135](https://github.com/GoodbyePlanet/semcode/commit/05cf135))

## [1.0.0](https://github.com/GoodbyePlanet/semcode/compare/v0.1.0...v1.0.0) (2026-05-06)

The project was renamed from `code-search-mcp` to **semcode** and the version set to `1.0.0`
([d2d2c50](https://github.com/GoodbyePlanet/semcode/commit/d2d2c50)). This entry covers the work that made
up that first feature-complete server.

### Features

* add BM25 sparse vectors and Reciprocal Rank Fusion for hybrid search ([12d82bc](https://github.com/GoodbyePlanet/semcode/commit/12d82bc))
* add optional Git history indexing into a separate `git_commits` collection ([c623d3e](https://github.com/GoodbyePlanet/semcode/commit/c623d3e)),
  extended to index diffs ([104d13d](https://github.com/GoodbyePlanet/semcode/commit/104d13d))
* add a `service_overview` MCP prompt ([180d712](https://github.com/GoodbyePlanet/semcode/commit/180d712))
* expose an HTTP endpoint for triggering reindex ([1a4c3a5](https://github.com/GoodbyePlanet/semcode/commit/1a4c3a5)),
  with progress reporting ([876b51c](https://github.com/GoodbyePlanet/semcode/commit/876b51c), [22a98ed](https://github.com/GoodbyePlanet/semcode/commit/22a98ed))
* add Tree-sitter parsers for Go ([052ac3f](https://github.com/GoodbyePlanet/semcode/commit/052ac3f)),
  TypeScript ([8e0ad35](https://github.com/GoodbyePlanet/semcode/commit/8e0ad35)),
  Markdown, Dockerfile and Docker Compose ([9473503](https://github.com/GoodbyePlanet/semcode/commit/9473503)),
  JSON ([b52f69e](https://github.com/GoodbyePlanet/semcode/commit/b52f69e)),
  HTML and CSS ([209bdc6](https://github.com/GoodbyePlanet/semcode/commit/209bdc6)),
  and XML ([edea704](https://github.com/GoodbyePlanet/semcode/commit/edea704))
* simplify `config.yaml` to repository selection and exclusions only ([88022c6](https://github.com/GoodbyePlanet/semcode/commit/88022c6))
* add the test setup ([9c79705](https://github.com/GoodbyePlanet/semcode/commit/9c79705))
* add a `Makefile` with dev convenience targets ([c41f71a](https://github.com/GoodbyePlanet/semcode/commit/c41f71a))
* release under the MIT license ([87e9977](https://github.com/GoodbyePlanet/semcode/commit/87e9977))

### Bug Fixes

* harden the indexing pipeline, GitHub client, and embedding provider ([576364a](https://github.com/GoodbyePlanet/semcode/commit/576364a))
* fix `get_context` for a file ([acbb916](https://github.com/GoodbyePlanet/semcode/commit/acbb916))
* fix indexing with a doubled root prefix ([4dbee16](https://github.com/GoodbyePlanet/semcode/commit/4dbee16))
* fix paths for Go services ([d0257fe](https://github.com/GoodbyePlanet/semcode/commit/d0257fe))

## 0.1.0 (2026-04-23)

* initial `code-search-mcp` scaffold: MCP server, Qdrant-backed symbol store, and the first Tree-sitter
  parsing pipeline ([d085d6d](https://github.com/GoodbyePlanet/semcode/commit/d085d6d))
