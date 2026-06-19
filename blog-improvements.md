# Blog Improvements

One-step fixes derived from comparing `blog.md` against `docs/`.

---

## Fix 1 — Replace invalid `symbol_type="api_route"` with `"function"`

In the `CodeSymbol` example at `blog.md:110-125`, change `symbol_type="api_route"` to `symbol_type="function"`. The valid types per `docs/ingestion.md:159` are `class`, `method`, `function`, `interface`, `enum`, `record`, `hook`, `component`, `type` — `api_route` is not one of them. The HTTP route metadata is already correctly carried in `extras`.

---

## Fix 2 — Rephrase the brace-bound `source` description

In `blog.md:91`, replace *"The complete raw text of the symbol from open brace to closing brace"* with *"The complete raw text of the symbol — from its declaration through the end of its body"*. The original wording doesn't fit Python (whitespace-delimited) and the surrounding example is Python.

---

## Fix 3 — Correct the "in a batch" embedding claim

In `blog.md:282-283` (Section 5, Step 3), replace *"calls both embedding providers in a batch"* with *"calls the dense and sparse providers sequentially with the file's batch of texts"*. The current wording implies parallel execution, but `docs/ingestion.md:186` notes the calls are awaited sequentially today.

---

## Fix 4 — Replace stylized sparse-vector illustration with the real shape

In `blog.md:157-162`, replace:
```
sparse = [{331: 0.5}, {14136: 0.7}]  # 20 key value pairs
```
with:
```
SparseVector(
    indices=[331, 14136, ...],   # vocabulary token IDs of non-zero terms
    values=[0.5, 0.7, ...],      # BM25 weights for each term
)
```
This matches the actual stored structure per `docs/sparse-vectors.md:81-85`.

---

## Fix 5 — Add the missing tokenizer transformations

In `blog.md:183-184` (Section 3, sparse input), extend the camelCase/snake_case description to include the other two transformations from `docs/sparse-vectors.md:46-52`: consecutive-caps split (`XMLParser` → `XML Parser`) and hyphen split (`place-order` → `place order`).

---

## Fix 6 — Add the RRF `k=60` constant and 2× over-fetch detail

In `blog.md:302-320` (Section 6), add a short paragraph after the worked example noting that Qdrant uses `k=60` as the RRF smoothing constant (so `1/(k+rank)` is concretely `1/61` for rank 1), and that each prefetch branch retrieves `limit * 2` candidates to give RRF a larger pool to re-rank. Source: `docs/retrieval-rrf.md:44, 62`.

---

## Fix 7 — Mention asymmetric passage/query encoding

In `blog.md:296-300` (Section 6 opening), add one sentence noting that the code-tuned dense providers (jina-api, voyage) use asymmetric encoding — passages are encoded with `task=retrieval.passage` / `input_type=document` at index time and queries with `task=retrieval.query` / `input_type=query` at search time. Source: `docs/dense-vectors.md:29, 90-94`.

---

## Fix 8 — Name the supported dense providers

In `blog.md:138-148` (Section 3, dense embeddings intro), add one sentence: *"semcode supports five dense providers — Jina (self-hosted), Jina API, Voyage, OpenAI, and Ollama — with vector sizes ranging from 768 to 3072 dimensions."* This grounds the abstract "hundreds or thousands of dimensions" claim. Source: `docs/dense-vectors.md:76-82`.

---

## Fix 9 — Add the GitHub Trees truncation caveat

In `blog.md:264-269` (Section 5, Step 1), append one sentence: *"For very large repositories, the Trees API response may be silently truncated by GitHub — semcode logs a warning but does not paginate or retry, so affected files are absent from the index run."* Source: `docs/ingestion.md:40`.

---

## Fix 10 — Note that displayed source can be stale

In `blog.md:323-334` (Conclusion), add one sentence mentioning that search results display source captured at index time, so post-index repo edits aren't reflected until reindex (the live-fetch `get_code_context` tool is the exception). Source: `docs/retrieval-rrf.md:182`.

---

## Fix 11 — Acknowledge name-lookup and live-context tools

In `blog.md:295-321` (Section 6) or the conclusion, add one sentence: *"Beyond semantic search, semcode also exposes direct symbol-name lookup (`find_symbol`) and a GitHub-backed `get_code_context` tool for retrieving full file or symbol source at request time."* Source: `docs/retrieval-rrf.md:96-150`.

---

## Fix 12 — Repair the section-break formatting

In `blog.md:130` and `blog.md:321`, insert a blank line before the `---` separator so it isn't glued to the previous content line.

---

## Fix 13 — Fix the awkward mid-sentence linebreak

In `blog.md:184`, reflow the sentence so `alongside` and `the original` aren't on separate lines mid-clause. Combine into a single line in the source.

---

## Fix 14 — Remove the stray space in the signature example

In `blog.md:121`, change `"async def list_users (db: Session) -> list[User]"` to `"async def list_users(db: Session) -> list[User]"` (no space before the opening paren).

---

## Fix 15 — Use correct code-fence language tags

In `blog.md`, change the ```` ```shell ```` fences at lines 52, 109, 145, 157 to the appropriate tag: `python` for the `CodeSymbol` example (line 109), and either no tag or `text` for the ASCII AST tree (line 52) and the vector illustrations (lines 145, 157).

---

## Fix 16 — Correct the `server/tools/search.py:60-71` citation

In `blog.md:232`, change the citation `server/tools/search.py:60-71` to `server/tools/search.py:55-71`. Verified against the source: the rendered-result block begins at line 55, not 60.

---

## Fix 17 — Replace or relocate the `pipeline.py:122-123` citation

In `blog.md:235`, the citation `server/indexer/pipeline.py:122-123` points at where `file_hash` and `indexed_at` are *written* into the payload, not where the skip decision is made. Either:
- Drop the citation (the bookkeeping description stands on its own), or
- Replace it with a citation to the hash-comparison step where `existing_hashes` is consulted (the actual "decide a file hasn't changed" logic).

---

## Fix 18 — Strengthen the payload-index citation

In `blog.md:243-247` (Section 4, payload indexes), the six-field list is correct — verified against `server/store/qdrant.py:80-94`. Add this file:line citation inline so readers can jump to the index-creation code.
