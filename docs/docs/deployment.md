---
id: deployment
title: Deployment
sidebar_position: 1.5
---

# Deployment

semcode runs as three containers defined in `docker-compose.yaml`: Qdrant, the semcode MCP server, and
(optionally) a local Jina embedding model served by HuggingFace TEI.

**Prerequisites:** Docker, and a GitHub token with `Contents: read` on the repos you want indexed. For running
the server outside Docker (stdio clients, development) you also need Python 3.12+ and
[uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env   # then set GITHUB_TOKEN
```

---

## Choosing an embedding path

**Path A — local Jina via TEI (default, no API key required):**

```bash
make docker-up-jina
# or: docker compose --profile jina up -d
```

**Path B — hosted provider (Voyage / OpenAI / Jina API) or local Ollama:**

```bash
# 1. In .env, set EMBEDDINGS_PROVIDER=voyage|openai|jina-api|ollama and the relevant API key / URL.
# 2. Then start without the jina profile — the jina-embeddings container will not start:
make docker-up
# or: docker compose up -d
```

:::warning No automatic fallback

The default `EMBEDDINGS_PROVIDER` is `jina`. If you start without `--profile jina` but leave the provider on the
default, semcode boots (Jina is `required: false` in compose) but the first embedding call fails with a
connection error.

:::

See [Configuration](configuration.md) for every provider variable, and
[Startup Validation](configuration.md#startup-validation) before switching providers on an existing index.

---

## Services

| Service                   | Profile | Port                         | Volume                                              | Purpose                |
|---------------------------|---------|------------------------------|-----------------------------------------------------|------------------------|
| **Qdrant**                | always  | `6333` (HTTP), `6334` (gRPC) | `qdrant_data`                                       | Vector DB              |
| **Jina Embeddings** (TEI) | `jina`  | `8087`                       | `embeddings_cache`                                  | Embedding model server |
| **semcode MCP**           | always  | `8090`                       | mounts `./config.yaml` read-only with `-with-config` | MCP + HTTP server      |

All services have health checks and persistent volumes. The server starts with empty collections — trigger an
initial index with the `reindex` MCP tool or [`POST /reindex`](http-api.md).

### Network exposure

Every port above is published on the host's loopback interface only (`127.0.0.1:<port>`). From the machine
running Docker everything works as usual (`http://localhost:8090/mcp`, the Qdrant dashboard, `make index-code`),
but other machines on the network cannot connect.

That is deliberate: none of these services is authenticated. Anyone who can reach port `8090` can search the
indexed (private) code and call `/reindex`, which spends your `GITHUB_TOKEN` quota and embedding credits, and
anyone who can reach `6333` can read or delete the Qdrant collections directly.

Inside the container semcode still binds to `0.0.0.0` (compose sets `MCP_HOST`), which Docker's port forwarding
requires. To make the server reachable from other machines, change its mapping to `"8090:8090"`, but only
behind your own authentication (for example a reverse proxy) and TLS. Keep Qdrant and the embedding server on
loopback or on a private Docker network.

---

## Curated services with `config.yaml`

You don't need a `config.yaml` at all — a missing file is treated as zero configured services, and repos can
register themselves through [`POST /reindex`](http-api.md#registering-a-repo-without-configyaml). That is why
`docker-compose.yaml` does **not** mount `config.yaml` by default, so `make docker-up` / `make docker-up-jina`
work out of the box.

If you also want curated services, copy `config.example.yaml` to `config.yaml` (see
[config.yaml Structure](configuration.md#configyaml-structure)) and use the `-with-config` targets, which layer
`docker-compose.config-yaml.yml` on top to add the mount:

```bash
make docker-up-with-config        # hosted provider
make docker-up-jina-with-config   # local Jina
# or: docker compose -f docker-compose.yaml -f docker-compose.config-yaml.yml up -d
```

Don't hand-edit the volume line in `docker-compose.yaml` itself — bind-mounting a `config.yaml` that doesn't exist
on the host silently creates an empty directory there, which breaks the server (surfaced as a clear error:
`CONFIG_PATH (...) is a directory, not a file`).

---

## GitHub token at scale

A single `GITHUB_TOKEN` reads every repo semcode indexes. For a handful of `config.yaml` entries, a fine-grained
PAT scoped to those repos is fine. For org-wide self-registration — where any repo can onboard itself just by
adding the [GitHub Actions workflow](https://github.com/GoodbyePlanet/semcode/blob/main/examples/github-actions/reindex-on-merge.yml)
— a PAT would need its repo list updated every time a new repo starts using it. A GitHub App installed org-wide
(all repositories, `Contents: read`) avoids that. GitHub Enterprise Server is supported via `GITHUB_API_URL`.

---

## Transports

The server speaks `streamable-http` by default at `http://localhost:8090/mcp`. Set `MCP_TRANSPORT` to change it:

- **`stdio`** — the MCP client spawns the server itself:
  `uv run --directory /path/to/semcode python -m server.main` with `MCP_TRANSPORT=stdio`. Qdrant must still be
  reachable (e.g. `docker compose up -d qdrant`) and dependencies installed (`uv sync`). `GITHUB_TOKEN`,
  `QDRANT_URL`, and the embedding variables are still read from `.env` in the project directory.
- **`sse`** — the legacy MCP HTTP transport, superseded by `streamable-http`. Only use it for clients that don't
  support `streamable-http` yet. The endpoint is `http://localhost:8090/sse`.

Client configuration snippets for each transport are in the
[README](https://github.com/GoodbyePlanet/semcode#-connecting-other-clients).
