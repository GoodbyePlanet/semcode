**Repository:** root
**Status:** Completed (2026-06-02)
**Created:** 2026-06-02
**Author:** lead

# RAG System Documentation

## Goal

Produce comprehensive documentation of the semcode RAG system covering: dense
vector ingestion, sparse vector (BM25) ingestion, hybrid retrieval with Reciprocal
Rank Fusion (RRF), and system configuration. The user is a participant throughout
the investigation — code analysis findings are shared with the user for input and
correction before each draft is written, and each draft is reviewed and approved by
the user before the file is saved to `docs/`. The documentation targets a mixed
audience (newcomers and experienced contributors) and includes observations on
design gaps and improvement opportunities per document.

## Context

- **User preferences:** one file per concern; mixed audience (concept intros for
  newcomers, design rationale for experienced contributors); include findings/observations
  per doc; human reviews each draft before it is saved; `docs/configuration.md` is a
  first-class deliverable, not just inline context.
- **No existing `docs/` folder** — it will be created as part of this plan.
- **Core files:**
  - `server/indexer/pipeline.py` — `IndexPipeline`, embedding text builders,
    ingestion orchestration, incremental indexing via blob SHA change detection
  - `server/store/qdrant.py` — `QdrantStore`, collection creation (named vectors
    `text-dense` + `text-sparse`), `upsert_chunks`, `search` with `FusionQuery(RRF)`
  - `server/tools/search.py` — MCP tools: `search_code`, `find_symbol`,
    `find_usages`, `get_code_context`
  - `server/embeddings/base.py` — `EmbeddingProvider` Protocol
  - `server/embeddings/factory.py` — registry pattern, singleton provider
  - `server/embeddings/bm25.py` — `BM25SparseProvider` using `fastembed` +
    `Qdrant/bm25`; uses `split_code_identifiers` pre-processing
  - `server/embeddings/code_tokenizer.py` — code identifier splitter for BM25
  - `server/embeddings/{jina,jina_api,voyage,openai,ollama}.py` — dense providers
  - `server/config.py` — `Settings` (pydantic-settings), `ServiceConfig`,
    `EmbeddingsProviderName`
- **Key design decisions visible in the code:**
  - Dual-text strategy: dense embeddings use a rich preamble with metadata;
    sparse (BM25) uses signature + docstring + source only
  - Incremental indexing: blob SHA comparison skips unchanged files
  - Deterministic point IDs: `uuid5` from `service:file_path:symbol_name:start_line`
  - RRF via Qdrant's native `FusionQuery(Fusion.RRF)` with 2× prefetch limit
  - Sparse vector stored in-memory (`on_disk=False`)
  - HNSW config: `m=16`, `ef_construct=128`; indexing threshold: 500
- **This is a documentation-only task** — no production code changes.

## Steps

- [x] Clarify requirements with user
- [x] Read codebase (pipeline, store, embeddings, config, tools)
- [x] Write plan
- [ ] Plan review cycle
- [ ] User plan approval
- [ ] Workflow selection
- [x] Task 1: Draft and review ingestion doc
- [x] Task 2: Draft and review dense vectors doc
- [x] Task 3: Draft and review sparse vectors doc
- [x] Task 4: Draft and review retrieval (RRF) doc
- [x] Task 5: Draft and review configuration doc
- [x] Task 6: Draft and review docs/README.md index + root README.md link
- [x] Commit all docs — bf0adea

## Tasks

### Task 1: docs/ingestion.md

Investigate the `IndexPipeline` end-to-end ingestion flow — share key findings
with the user before drafting, then write the document.

**Investigation scope:** how a service is discovered, how files are fetched and
filtered, how symbols are parsed, how both embedding types are generated, and how
results are upserted into Qdrant; incremental indexing (blob SHA change detection);
stale-entry cleanup.

**Process:**
1. Present code analysis findings and observations to the user via AskUserQuestion;
   proceed to drafting only after user confirms the findings are accurate.
2. Write the draft; present it to the user for review via AskUserQuestion.
3. Save `docs/ingestion.md` only after the user approves the draft.

Acceptance criteria:
- File `docs/ingestion.md` exists with sections: Overview, Pipeline Stages
  (Discovery → Parsing → Embedding → Upsert → Cleanup), Incremental Indexing,
  Data Model (what a `CodeSymbol` and its payload look like), Observations
- File written to disk only after user's explicit approval of the draft
- No production code is modified

### Task 2: docs/dense-vectors.md

Investigate how dense embeddings are produced — share key findings with the user
before drafting, then write the document.

**Investigation scope:** `EmbeddingProvider` Protocol, the factory/registry
pattern, five concrete providers (jina local, jina API, voyage, openai, ollama),
the rich preamble text strategy in `_build_embedding_text`, the 6000-char
truncation limit, provider selection at startup.

**Process:**
1. Present code analysis findings and observations to the user via AskUserQuestion;
   proceed to drafting only after user confirms the findings are accurate.
2. Write the draft; present it to the user for review via AskUserQuestion.
3. Save `docs/dense-vectors.md` only after the user approves the draft.

Acceptance criteria:
- File `docs/dense-vectors.md` exists with sections: Overview, Provider Protocol,
  Embedding Text Strategy (preamble construction), Supported Providers (comparison
  table), Provider Selection, Observations
- File written to disk only after user's explicit approval of the draft
- No production code is modified

### Task 3: docs/sparse-vectors.md

Investigate how sparse BM25 embeddings are produced — share key findings with the
user before drafting, then write the document.

**Investigation scope:** `BM25SparseProvider`, `Qdrant/bm25` fastembed model,
`split_code_identifiers` pre-processing (and why it matters for code), distinction
between `passage_embed` and `query_embed`, sparse vector structure
(`indices` + `values`).

**Process:**
1. Present code analysis findings and observations to the user via AskUserQuestion;
   proceed to drafting only after user confirms the findings are accurate.
2. Write the draft; present it to the user for review via AskUserQuestion.
3. Save `docs/sparse-vectors.md` only after the user approves the draft.

Acceptance criteria:
- File `docs/sparse-vectors.md` exists with sections: Overview, BM25 for Code
  (why BM25 complements dense), Code Tokenizer Pre-processing, Passage vs Query
  Embedding, Sparse Vector Structure, Observations
- File written to disk only after user's explicit approval of the draft
- No production code is modified

### Task 4: docs/retrieval-rrf.md

Investigate the hybrid retrieval path — share key findings with the user before
drafting, then write the document.

**Investigation scope:** `QdrantStore.search` dual-prefetch (dense + sparse, each
at 2× limit), Qdrant's native RRF fusion, `find_by_name` fallback (exact scroll vs.
substring scan), four MCP tool entry points (`search_code`, `find_symbol`,
`find_usages`, `get_code_context`), result formatting for MCP clients.

**Process:**
1. Present code analysis findings and observations to the user via AskUserQuestion;
   proceed to drafting only after user confirms the findings are accurate.
2. Write the draft; present it to the user for review via AskUserQuestion.
3. Save `docs/retrieval-rrf.md` only after the user approves the draft.

Acceptance criteria:
- File `docs/retrieval-rrf.md` exists with sections: Overview, Hybrid Search
  Architecture, RRF Fusion, MCP Tool Interface, Result Formatting, Observations
- File written to disk only after user's explicit approval of the draft
- No production code is modified

### Task 5: docs/configuration.md

Investigate all configuration knobs — share key findings with the user before
drafting, then write the document.

**Investigation scope:** every env var in `Settings` (name, default, which
provider it applies to), `config.yaml` service fields (`name`, `github_repo`,
`github_ref`, `root`, `exclude`), collection settings, transport settings, startup
dimension-mismatch validation.

**Process:**
1. Present code analysis findings and observations to the user via AskUserQuestion;
   proceed to drafting only after user confirms the findings are accurate.
2. Write the draft; present it to the user for review via AskUserQuestion.
3. Save `docs/configuration.md` only after the user approves the draft.

Acceptance criteria:
- File `docs/configuration.md` exists with sections: Overview, Environment
  Variables (table: var, default, description), config.yaml Structure, Startup
  Validation, Observations
- File written to disk only after user's explicit approval of the draft
- No production code is modified

### Task 6: docs/README.md + root README.md link

Write a one-page index that describes the system at a glance (what semcode RAG
is, what it indexes, how it serves queries), lists the five topic docs with
one-line descriptions (ingestion.md, dense-vectors.md, sparse-vectors.md,
retrieval-rrf.md, configuration.md), and provides a quick-start pointer to
`docs/configuration.md`. Then add a link from the root `README.md` into the
new `docs/` tree so readers arriving at the project's entry point can discover
the detailed documentation.

**Process:**
1. Present draft of `docs/README.md` to the user for review via AskUserQuestion.
2. Save `docs/README.md` only after the user approves the draft.
3. Add a "Documentation" section to the root `README.md` linking to
   `docs/README.md` with a one-line description; present the addition to the user
   before saving.

Acceptance criteria:
- File `docs/README.md` exists with sections: What is semcode RAG, Documentation
  Index (links to the five topic docs: ingestion, dense-vectors, sparse-vectors,
  retrieval-rrf, configuration), Quick Start
- Root `README.md` contains a link to `docs/README.md`
- Both files written to disk only after user's explicit approval
- No production code is modified

## Decisions

- **One file per concern:** user preference — separate files for ingestion, dense
  vectors, sparse vectors, retrieval, and configuration; plus README index.
- **Two-checkpoint workflow per document:** (1) findings are shared with the user
  via AskUserQuestion before drafting begins — the user can correct or redirect
  the analysis; (2) the draft is presented to the user before the file is written
  to disk. This fulfills the "human in every part of the investigation" requirement
  at both the analysis and the writing stage.
- **Observations included:** each doc has a findings/observations section surfacing
  design gaps and improvement ideas — user preference.
- **Mixed audience:** docs include brief concept intros (what RAG is, what BM25 is)
  alongside design-specific detail.
- **docs/ coexists with root README.md:** the existing root `README.md` already
  covers the RAG system at a high level (indexing, embedding providers, env vars).
  The new `docs/` files provide deeper, structured documentation of each concern.
  Rather than rewrite or condense the root README, this plan adds only a
  "Documentation" link section pointing to `docs/README.md`. The two sources are
  complementary: the root README serves as a project overview and quick-start;
  `docs/` serves as the authoritative deep-dive reference.
- **No production code changes:** this plan produces only markdown files in `docs/`
  and a minor link addition to the root `README.md`.

## Non-Goals

- Documenting the parser subsystem (`server/parser/`) — out of scope; not part of
  the RAG ingestion or retrieval path.
- Documenting git history indexing (`server/indexer/git_history.py`,
  `server/store/commit_store.py`) — separate concern from the RAG system.
- Making code changes to fix observed gaps — observations are documented only;
  improvements are a separate plan.
