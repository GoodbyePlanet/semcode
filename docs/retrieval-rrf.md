# Retrieval: Hybrid Search with RRF

This document covers how semcode searches the Qdrant index: the dual-prefetch architecture, how Reciprocal Rank Fusion merges the dense and sparse result lists, the name-lookup fallback, and the four MCP tool entry points available to AI clients.

---

## Overview

semcode uses **hybrid search** — combining dense semantic vectors and sparse BM25 vectors in a single query. The fusion algorithm is **Reciprocal Rank Fusion (RRF)**, which re-ranks results based on their position in each sub-ranking rather than their raw scores. This approach consistently outperforms either method alone:

- Dense search finds semantically similar code even when exact identifier names are absent
- Sparse search finds exact and near-exact identifier matches that dense models may rank lower
- RRF combines both without requiring score calibration across the two different vector spaces

---

## Hybrid Search Architecture

The main search path is `QdrantStore.search()` (`server/store/qdrant.py`). A single Qdrant query with two prefetch branches replaces what would otherwise be two separate requests:

```python
result = await self._client.query_points(
    collection_name=self._collection,
    prefetch=[
        Prefetch(
            query=dense_vector,
            using="text-dense",
            limit=limit * 2,  # over-fetch for RRF
            filter=query_filter,
        ),
        Prefetch(
            query=sparse_vector,
            using="text-sparse",
            limit=limit * 2,  # over-fetch for RRF
            filter=query_filter,
        ),
    ],
    query=FusionQuery(fusion=Fusion.RRF),
    limit=limit,
    with_payload=True,
)
```

**2× prefetch multiplier:** each branch retrieves twice the requested limit (e.g., 20 candidates when `limit=10`). This gives RRF a larger candidate pool to re-rank, which improves final result quality compared to fetching exactly `limit` results from each branch.

**Service filter:** when a `service` name is provided, a `Filter(must=[FieldCondition('service', ...)])` is applied to both prefetch branches simultaneously. A search filtered to one service only retrieves candidates from that service's symbols.

---

## RRF Fusion

Reciprocal Rank Fusion combines two ranked lists using the formula:

```
score(d) = Σ  1 / (k + rank_i(d))
           i
```

Where:
- `d` is a document (indexed symbol)
- `rank_i(d)` is the document's rank (1-based) in result list `i` (dense or sparse)
- `k` is a smoothing constant (Qdrant's default: **60**)

A document that ranks 1st in both the dense and sparse results gets `1/(60+1) + 1/(60+1) ≈ 0.033`. A document that ranks 1st in only one list gets `1/(60+1) ≈ 0.016`. A document absent from one list still contributes via the other, but at a lower score.

The smoothing constant `k=60` is Qdrant's internal default for `Fusion.RRF`. It is not exposed as a configurable parameter in semcode.

---

## Name Lookup: `find_by_name`

`find_by_name()` is a non-vector fallback for direct symbol lookup. It supports two modes:

### Exact mode (`exact=True`)

Queries Qdrant with a keyword filter on the `symbol_name` payload field:

```python
FieldCondition(key="symbol_name", match=MatchValue(value=name))
```

Returns up to 20 exact matches via a scroll operation. `symbol_name` carries a `KEYWORD` payload index, so this filter is served by Qdrant. Additional filters for `symbol_type` and `service` are stacked into the same `must` list. No vectors are fetched.

### Partial mode (`exact=False`, default)

Matching is **token-aware and case-insensitive**, served server-side by a full-text payload index.

At index time, `_symbol_to_payload()` stores a derived `symbol_name_tokens` field built by `symbol_name_tokens()`. It contains three things: the original identifier, its camelCase/PascalCase/snake_case subwords (via the same `split_code_identifiers()` helper that feeds BM25), and *suffix joins* — the identifier re-joined from each subword boundary onwards. That field carries a `TEXT` index with the `PREFIX` tokenizer (`lowercase=True`, token length 2–30), and `find_by_name` queries it with a single `MatchText`-filtered scroll returning up to 50 matches.

**Why suffix joins.** A `PREFIX` index only matches a query that prefixes a stored token. Storing just the identifier and its subwords means `GetWebAuthnSession` is reachable by `GetWeb` (prefix of the whole name) and by `Authn` (a subword), but *not* by `WebAuth` — that query spans `Web` + `Authn` and is not anchored at the start of the name. The old client-side substring scan found it, so without the joins this would be a silent recall regression: `WebAuth` returned 12 of 18 real matches on a live collection. Emitting `WebAuthnSession`, `AuthnSession`, `Session` as their own tokens makes every subword-boundary query a real index hit. Joins are capped at the first `MAX_SUFFIX_JOIN_SUBWORDS` (8) subwords and skipped entirely for names containing whitespace — markdown headings, CSS selector lists and dependency coordinates are prose, whose words are already separate tokens.

Matching a query against `placeOrderRequest`, measured against a real Qdrant:

| Query | Matches | Latency | Why |
| --- | --- | --- | --- |
| `order` | ✅ | ~2 ms | full subword token — indexed lookup |
| `ord`, `plac`, `reques` | ✅ | ~2 ms | `PREFIX` tokenizer indexes every token prefix |
| `orderRequest` | ✅ | ~2 ms | suffix join — indexed lookup |
| `place order` | ✅ | — | `MatchText` requires all query tokens to match |
| `rder`, `quest` | ✅ | O(N) | mid-token: no index hit, served by the client-side fallback (see below) |

Results are then ranked exact name → prefix → remainder, because Qdrant returns scrolled points in point-id order and would otherwise bury the exact hit.

**Mid-token queries are not served by the index, and cost O(N) client-side.** A fragment that is not a prefix of any stored token (`rder` inside `placeOrderRequest`) produces **zero** rows from Qdrant — the `PREFIX` tokenizer indexes token prefixes only, and Qdrant does not silently scan on your behalf. Such queries land in `_find_by_name_scanning()` below. Qdrant offers no n-gram tokenizer, so arbitrary-substring matching cannot be made sublinear. What issue [#72](https://github.com/GoodbyePlanet/semcode/issues/72) removed is the client-side scan for *token and subword-boundary* queries, which are the overwhelming majority.

**Fallback.** When the full-text filter returns zero results, `_find_by_name_scanning()` runs the pre-#72 behaviour — scroll in batches of 200 and substring-match `symbol_name` in Python. Two distinct cases reach it, indistinguishable from each other: a mid-token fragment, and a collection indexed before `symbol_name_tokens` existed (where `MatchText` on the absent field matches nothing). A genuinely unmatched query such as `zzz` also triggers it, and is the worst case — it scans the entire collection to return nothing. Measured cost of that scan: 0.9 s at 50k symbols, 8.8 s at 250k, linear thereafter.

**Migrating an existing collection.** The payload indexes are created on every startup, including for collections that predate them, so no collection drop is needed. But populating `symbol_name_tokens` requires the points to be rewritten, and incremental indexing compares Git blob SHAs and skips unchanged files — a plain `make index-code` on an unchanged repo reports `{"files": 0, "chunks": 0, "skipped": N}` and leaves the field empty. Use a **force** reindex:

```bash
curl -X POST http://localhost:8090/reindex -H 'Content-Type: application/json' -d '{"force": true}'
```

This re-embeds every symbol, so it costs a full pass of embedding-provider calls (709 symbols took ~4 minutes on a hosted provider). Until it runs, partial lookups keep working via the fallback scan.

---

## MCP Tool Interface

semcode exposes four search tools to AI clients via the MCP protocol (`server/tools/search.py`). All tools read from the singleton store via `server/state.py`.

### `search_code`

```
search_code(query: str, service: str | None, chunk_tier: str | None, limit: int = 10) -> str
```

The primary semantic search tool. At query time:

1. Embeds the query string with both the dense provider (`embed_query`) and the sparse provider (`embed_query`)
2. Calls `store.search()` with both vectors → RRF fusion, optionally scoped to `chunk_tier` (`"method"` or `"class"`)
3. Returns a formatted Markdown string with up to `limit` results

Each result includes: symbol name and type, RRF score, file location (path + line range), service, language, annotations, HTTP route (if present), and the symbol's signature or source (first 500 characters from the payload).

### `find_symbol`

```
find_symbol(name: str, symbol_type: str | None, service: str | None, chunk_tier: str | None, exact: bool = False) -> str
```

Name-based lookup via `store.find_by_name()`. Does not use vectors or RRF. Supports filtering by `chunk_tier` (`"method"` or `"class"`) in addition to `symbol_type` and `service`. Returns up to 20 (exact) or 50 (partial) matches, exact names first. Each result includes: name, type, location, package, parent class, and source (first 800 characters).

### `find_usages`

```
find_usages(symbol_name: str, service: str | None, limit: int = 10) -> str
```

Finds code that references a given symbol name. Constructs the query:

```python
query = f"code that uses or references {symbol_name}"
```

Uses RRF hybrid search (same path as `search_code`), then filters out results whose `symbol_name` exactly matches the input (to exclude the symbol's own definition). Returns a snippet of source code centered around the first occurrence of `symbol_name` in each result's source.

Since this tool relies on a natural-language query wrapper, result quality depends on the dense model's ability to associate the phrase "uses or references X" with callers of X.

### `get_code_context`

```
get_code_context(file_path: str, symbol_name: str | None) -> str
```

Returns full source code for a file or a specific symbol. Unlike the other tools, it **fetches live from GitHub** rather than returning Qdrant payload content:

1. Calls `store.get_file_info(file_path)` to resolve the service name
2. Looks up the service's `github_repo` and `github_ref` via `load_effective_services()` — `config.yaml` or the
   dynamic service registry (see [configuration.md](configuration.md#dynamic-service-registration))
3. Fetches the raw file content from GitHub (path-based, not blob SHA)
4. If `symbol_name` is given: calls `find_by_name(exact=True)` to get stored line numbers, then slices the file; falls back to a text search if the symbol isn't in the index

---

## Result Formatting

All four tools return plain Markdown strings, not structured objects. This format is optimised for consumption by an AI assistant reading the tool output:

```markdown
### 1. `processOrder` (method) — score 0.032
**Location**: `catalog-service/src/main/OrderService.java:42-78`
**Service**: catalog-service | **Language**: java
**Annotations**: @PostMapping, @Transactional
**Route**: POST /orders

\`\`\`java
public OrderResult processOrder(OrderRequest request) {
    ...
\`\`\`
```

---

## Observations

**RRF constant is not configurable** — Qdrant's `k=60` default is used. There is no way to adjust this via configuration. The choice of `k` affects how strongly RRF rewards documents appearing in both lists versus only one. A lower `k` amplifies the benefit of appearing in both; a higher `k` makes the fusion more uniform.

**Mid-token queries are still O(N), on the client** — `find_by_name` with `exact=False` is served by the `symbol_name_tokens` full-text index, but only a query prefixing the identifier, one of its subwords, or one of its suffix joins is a real index hit (~2 ms, flat from 50k to 250k symbols). A mid-token fragment such as `rder` is not a prefix of any stored token, so Qdrant returns nothing and `_find_by_name_scanning()` pages the collection over the wire instead — 0.9 s at 50k symbols, 8.8 s at 250k. Qdrant offers no n-gram tokenizer, so there is no index that would make arbitrary-substring matching sublinear. Note that a query matching *no* symbol pays this same full scan.

**Token semantics differ from substring matching** — now that lookups are token-aware, `Auth` no longer matches `oauth_db` or `oauth2-session`: `auth` is not a prefix of the token `oauth2`. This is intentional, and differs from the pre-#72 substring scan. Subword-boundary queries (`WebAuth` → `GetWebAuthnSession`) *are* matched, via suffix joins.

**`find_usages` depends on dense quality** — the "code that uses or references X" query wrapper is a heuristic. If the dense model doesn't associate the phrasing with caller patterns, results will be poor. There is no static call-graph analysis; the tool is entirely retrieval-based.

**`get_code_context` has no caching** — every call fetches from GitHub. If the same file is requested multiple times in a session, the GitHub API is hit each time. A file deleted or renamed in the repo after the last index run will return a 404 even if Qdrant still holds its indexed symbols.

**Source in search results may be stale** — `search_code`, `find_symbol`, and `find_usages` display source from the Qdrant payload, which was captured at index time. If the file has changed in the repo since the last index run, the displayed source is the old version. `get_code_context` always shows the current GitHub version.
