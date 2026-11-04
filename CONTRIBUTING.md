# Contributing to semcode

Thanks for your interest in improving semcode! Bug reports, feature ideas and pull requests are all welcome.
For anything larger than a small fix, please [open an issue](https://github.com/GoodbyePlanet/semcode/issues)
first so we can agree on the approach.

## Development setup

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker, and a GitHub token.

```bash
git clone https://github.com/GoodbyePlanet/semcode && cd semcode
uv sync --group dev          # runtime + test dependencies
cp .env.example .env         # set GITHUB_TOKEN

docker compose --profile jina up -d qdrant jina-embeddings   # Qdrant + local embeddings
uv run python -m server.main                                  # server on http://localhost:8090/mcp
```

Or run the whole stack in Docker with `make docker-up-jina` (rebuild after changes with
`make docker-build-restart-jina`). See the [Deployment docs](https://goodbyeplanet.github.io/semcode/deployment)
for the other options.

## Tests

```bash
uv run pytest                          # everything
uv run pytest tests/parser/            # parser tests only
uv run pytest tests/test_pipeline.py   # a single file
```

- `tests/parser/test_*.py` — one file per language; snapshots parser behaviour against canonical fixtures in
  `tests/fixtures/<language>/`
- `tests/test_pipeline.py`, `tests/test_store.py`, `tests/test_git_history.py` — indexing pipeline and Qdrant store
- `tests/test_reindex_route.py` — HTTP route tests
- `tests/embeddings/` — embedding provider tests

Async tests use `asyncio_mode = "auto"` (pytest-asyncio), and HTTP calls are mocked with `respx`.

## Project structure

```
server/
├── main.py          # MCP server entry point + lifespan
├── config.py        # Settings and service configuration
├── state.py         # Shared store singletons
├── parser/          # Tree-sitter parsers, one file per language
├── embeddings/      # Pluggable dense providers (Jina/Voyage/OpenAI/Ollama) + BM25 sparse + code identifier tokenizer
├── indexer/         # GitHub fetcher, code indexing pipeline, git history pipeline
├── store/           # Qdrant vector stores (code_symbols hybrid + git_commits dense + service registry)
├── tools/           # MCP tool implementations (search, index, history, admin)
├── prompts/         # MCP prompt templates (service_overview, system_design_overview)
└── routes/          # HTTP routes (reindex, reindex-history)
docs/                # Docusaurus site published to goodbyeplanet.github.io/semcode
```

The [docs site](https://goodbyeplanet.github.io/semcode/) explains the ingestion and retrieval internals in depth.
To preview it locally: `cd docs && npm install && npm start`.

## Adding a language

1. Implement a parser in `server/parser/<language>.py` that satisfies the `LanguageParser` protocol from
   `base.py` and returns `CodeSymbol` objects. Extract framework metadata into `extras` where it matters
   (routes, stereotypes, …).
2. Register it in `server/parser/registry.py` (file extensions / filenames).
3. Add canonical fixture files under `tests/fixtures/<language>/`.
4. Add snapshot tests under `tests/parser/test_<language>.py`.

## Commit messages and pull requests

Releases are automated with [release-please](https://github.com/googleapis/release-please), so commit messages
drive the version number and the changelog. They must follow
[Conventional Commits](https://www.conventionalcommits.org/).

PRs are squash-merged and **the PR title becomes the commit on `main`**, so the PR title must itself be a
well-formed Conventional Commit (e.g. `feat: add Elixir parser`, `fix: handle empty config.yaml`). Maintainers:
the repo should have *"Default to PR title for squash merges"* enabled.

| Commit prefix                                    | Bump  | Changelog section        |
|--------------------------------------------------|-------|--------------------------|
| `feat!:` / `BREAKING CHANGE:`                    | major | ⚠ Breaking Changes       |
| `feat:`                                          | minor | Features                 |
| `fix:`                                           | patch | Bug Fixes                |
| `perf:`                                          | patch | Performance Improvements |
| `deps:`                                          | patch | Dependencies             |
| `refactor:`                                      | patch | Code Refactoring         |
| `docs:` `test:` `style:` `chore:` `ci:` `build:` | patch | hidden                   |

Major is reserved for breaking changes to the **MCP tool signatures or the config schema** — the surfaces clients
and deployments depend on. Dependabot uses the `deps` prefix, so a week of dependency updates still produces a
patch release that marks which dependency set was tested together.

## Versioning and releases

- The version lives in **one place**: `version` in `pyproject.toml`. `server/main.py` reads it back through
  `importlib.metadata.version("semcode")` and reports it as the MCP `serverInfo.version`.
- **Never edit that version by hand**, and never hand-edit `CHANGELOG.md` above the `1.1.0` heading — both are
  owned by release-please.

How a release happens (`.github/workflows/release.yml`):

1. Commits land on `main` using Conventional Commits.
2. release-please opens (or updates) a `chore(main): release X.Y.Z` PR that bumps `pyproject.toml` and writes
   `CHANGELOG.md` from those commit messages.
3. Merging that PR tags the commit `vX.Y.Z` and cuts a GitHub Release. Nothing is released until a human merges it.

A release currently produces a GitHub Release with the source and generated changelog. Nothing is published to
PyPI, and no container image is pushed — semcode is built locally from the `Dockerfile`.

The release PR is created with `GITHUB_TOKEN`, which by design does not trigger other workflows — CI does not
re-run on the release PR itself. The commits it releases were already tested on `main`.
