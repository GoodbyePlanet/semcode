# semcode RAG System — Documentation

semcode is an MCP server that provides **hybrid semantic search over code** from GitHub repositories. It parses source files into code symbols (classes, methods, functions) using Tree-sitter, indexes them with both dense and sparse embedding vectors, and retrieves them using Reciprocal Rank Fusion (RRF).

**What it indexes:** code symbols from any configured GitHub repository. Each symbol (class, method, function, interface) is stored as a Qdrant point with its source text, metadata, and two embedding vectors.

**How it serves queries:** AI clients connect via MCP and call tools like `search_code`, `find_symbol`, and `find_usages`. Each search runs a hybrid query — dense semantic vectors find conceptually similar code; BM25 sparse vectors find exact and partial identifier matches. RRF merges both rankings into a single ordered result list.

---

## Documentation Index

| Document | What it covers |
|----------|---------------|
| [ingestion.md](ingestion.md) | End-to-end indexing pipeline: GitHub file discovery, incremental change detection, parsing, embedding, upsert, and stale cleanup |
| [dense-vectors.md](dense-vectors.md) | Dense embedding providers (Jina, Voyage, OpenAI, Ollama), the embedding text strategy, and provider selection |
| [sparse-vectors.md](sparse-vectors.md) | BM25 sparse embeddings, the code identifier tokenizer, and the sparse vector format |
| [retrieval-rrf.md](retrieval-rrf.md) | Hybrid search architecture, RRF fusion, name lookup, and the four MCP tool entry points |
| [configuration.md](configuration.md) | All environment variables, `config.yaml` structure, and startup validation |

---

## Quick Start

1. **Configure services** — copy `config.example.yaml` to `config.yaml` and add your GitHub repositories. See [configuration.md](configuration.md) for all fields.
2. **Set environment variables** — copy `.env.example` to `.env` and set at minimum `GITHUB_TOKEN`. The default embedding provider (`jina`) requires a locally running TEI container; for a hosted alternative, set `EMBEDDINGS_PROVIDER=voyage` and `VOYAGE_API_KEY=...`.
3. **Start Qdrant and the server** — `make docker-up-jina` (local Jina) or `make docker-up-voyage` (Voyage API), then connect your MCP client to `http://localhost:8090`.

For full setup instructions, see the root [README](../README.md).
