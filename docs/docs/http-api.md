---
id: http-api
title: HTTP API
sidebar_position: 7
---

# HTTP API

Alongside the MCP tools, the server exposes two HTTP endpoints for triggering indexing from CI/CD or
external schedulers. They are served on the same port as MCP (`8090` by default).

---

## Endpoints

| Endpoint                | Body                                                                                                                                                    | Description                                  |
|-------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------|
| `POST /reindex`         | `{"service": "<name>"?, "force": <bool>?, "source": "github"\|"gitlab"?, "repo": "<owner/repo>"?, "ref": "<ref>"?, "root": "<path>"?, "exclude": [<glob>, ...]?}` | Reindex one or all services — returns NDJSON |
| `POST /reindex-history` | `{"service": "<name>"?, "force": <bool>?}`                                                                                                              | Index git commit history — returns NDJSON    |

All bodies are optional — omit `service` to act on all services, omit `force` for incremental indexing.
Both endpoints stream **newline-delimited JSON** (one frame per line) so you can consume progress in real
time from CI/CD pipelines or any other client.

```bash
# Incremental reindex of every service
curl -N -X POST http://localhost:8090/reindex -H 'Content-Type: application/json'

# Re-embed one service from scratch
curl -N -X POST http://localhost:8090/reindex -H 'Content-Type: application/json' \
  -d '{"service": "catalog-service", "force": true}'
```

The Makefile wraps the no-body forms as `make index-code` and `make index-history`.

---

## Registering a repo without `config.yaml`

If the `POST /reindex` body includes `repo` (or its alias `github_repo`), the `service` name is registered with that repo
definition before indexing runs — `service` is required in this case. The registration is persisted, so it
survives restarts and behaves like a `config.yaml` service from then on. `ref` (alias `github_ref`) defaults to `main` and `source` defaults to `github`;
`root` and `exclude` mirror the same fields in `config.yaml`. A `service` name already defined in
`config.yaml` always wins over one registered this way.

```bash
curl -N -X POST http://localhost:8090/reindex -H 'Content-Type: application/json' \
  -d '{"service": "catalog-service", "repo": "my-org/my-repo"}'
```

See [Dynamic Service Registration](configuration.md#dynamic-service-registration) for how registrations are
stored and resolved, and the
[GitHub Actions example](https://github.com/GoodbyePlanet/semcode/blob/main/examples/github-actions/reindex-on-merge.yml)
for a drop-in workflow that self-registers a repo and reindexes it on every merge.

:::warning No authentication

Neither endpoint is authenticated. An unauthenticated caller can make the server index — and permanently
register — any repo `GITHUB_TOKEN` can read. Put the HTTP API behind your own network boundary or
reverse-proxy auth before exposing it.

:::

---

## Frame shapes

```jsonc
// in-flight progress
{"type": "progress", "phase": "discovery|upserting|cleanup", "current": 12, "total": 200, "percentage": 6.0, "service": "my-service"}
// final summary (one per request)
{"type": "done", "result": {"files": 42, "chunks": 318, "skipped": 5}}
// emitted instead of "done" on failure
{"type": "error", "message": "..."}
```

For `/reindex` the `upserting` frames carry `current` as a monotonically increasing count of files
resolved — indexed, skipped as unchanged, or dropped by a fetch/parse failure — so it always ends at
`total`. Files are indexed concurrently, so frames are emitted per batch rather than per file.

For `/reindex-history` the `phase` value is `discovery|embedding|upserting` and the `done` result is
`{"new": int, "skipped": int, "diff_updated": int}`.
