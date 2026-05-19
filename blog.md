# Blog Post Plan: How semcode Builds a RAG System for Code Search

## Context

This blog post explains the RAG (retrieval-augmented generation) pipeline behind
[**semcode**](https://github.com/GoodbyePlanet/semcode), an MCP server that does
semantic code search across your GitHub repositories. It covers both parts of the pipeline: the **ingestion** side — how
repositories are found, how code is parsed into symbols with Tree-sitter, how embedding inputs are constructed both
dense and sparse, and how
points land in Qdrant incrementally — and the **retrieval** side — how queries are encoded into both dense and sparse
vectors and fused server-side with RRF (Reciprocal Rank Fusion). Along the way we'll cover why a hybrid dense+sparse
approach beats either one alone for code, and why the *payload* stored next to each vector matters as much as the vector
itself.

Audience: engineers familiar with RAG, embeddings, and vector DBs, curious about applying RAG to source code
specifically (not prose).

---

## Section 1 — Why RAG for code is different from RAG for documents

Most RAG systems are built around prose — PDFs, internal documentation, wikis... The content is natural language written
for humans, meaning is carried in sentences, and semantic search over plain text works well, and when you add second
stage retrieval (reranker), you get a system that can answer your questions with high confidence.
Software code is different: it's structured, symbolic, it's written for compilers and interpreters. Meaning is
distributed across structure, not sentences:

- A function name (retryWithBackoff) carries intent
- The signature (attempts: int, delay_ms: int) carries contract
- The body carries implementation details
- Annotations (@Retryable, @CircuitBreaker) carry framework behavior
- The class it belongs to (OrderProcessingService) carries domain context

None of that is a sentence. You can't chunk code by paragraph — you chunk by symbol (function, class, method).
Let's see how that is implemented in **semcode**.

---

## Section 2 — From source files to Code Symbols - Tree-sitter parsing

What is an AST?

An Abstract Syntax Tree is a tree representation of source code's grammatical structure (logical parts of this code and
how do they relate to each other). Every construct in your code —
a function definition, a class, an if statement, a variable assignment — becomes a node in the tree, where parent-child
relationships express nesting and ownership.

For clarity, bellow is a pruned AST. Just to give you a mental model of how a parser sees
a function: a decorated async definition with typed parameters, a return annotation, and a body containing a
docstring and a single return.

```shell
@app.get("/users")
async def list_users(db: Session) -> list[User]:
    """Return all users."""
    return db.query(User).all()

module
└── decorated_definition
    ├── decorator              → "@app.get("/users")"
    └── function_definition
        ├── name               → "list_users"
        ├── parameters         → "(db: Session)"
        ├── return_type        → "list[User]"
        └── body
            ├── expression_statement
            │   └── string     → '"""Return all users."""'
            └── return_statement
```

What is Tree sitter?

Tree-sitter is a parser generator tool and an incremental parsing library. It can build a concrete syntax tree for a
source file and efficiently update the syntax tree as the source file is edited.
[Tree-sitter official documentation](https://tree-sitter.github.io/tree-sitter/)

What is a Code Symbol in **semcode**?

A symbol is one named, self-contained unit of code that a language considers meaningful — a function, a class, a method,
an interface, a React component, a hook... In **semcode** a symbol is a CodeSymbol dataclass,
which captures everything needed to search, understand, and locate it without reading the surrounding file.

What a `CodeSymbol` carries:

**name / symbol_type / language** — These uniquely describe what kind of thing this is (save,
method, java) so retrieval can filter by language or type before even looking at embeddings.

**signature** — The declaration line only, e.g. *def save(self, db: Session) -> User*. This is what you'd see in an
IDE's autocomplete popup — compact enough to show in search results without including the full body.

**source** — The complete raw text of the symbol from open brace to closing brace. This is what gets embedded into the
vector store, giving the model the full implementation context when a chunk is retrieved.

**start_line / end_line** — Position recorded by Tree-sitter during parsing, used to link a search result back
to an exact location in the file.

**parent_name / package** — Structural context. **parent_name** says which class owns this method; **package** says
which Java
package or Python module the file belongs to. Without these, two methods both named save in different services are
indistinguishable.

**annotations / extras** — Language-specific enrichment. A Java @GetMapping("/users") lands in annotations; the
extracted
HTTP route string (GET /users) lands in extras. For TypeScript, extras flags whether a component uses hooks, or whether
a function matches the React component signature pattern.

Example:

```shell
CodeSymbol(
    name="list_users",
    symbol_type="api_route",
    language="python",
    source="async def list_users(db: Session) -> list[User]:\n    ...",
    file_path="auth-service/routers/users.py",
    start_line=2,
    end_line=4,
    parent_name=None,
    package="auth-service.routers.users",
    annotations=["app.get(\"/users\")"],
    signature="async def list_users (db: Session) -> list[User]",
    docstring='"""Return all users."""',
    extras={"is_async": True, "http_method": "GET", "http_route": "/users"},
)
```

So the full pipeline is:
Tree-sitter parses code into an AST. The parser goes through that AST node by node, asks each node where it starts/ends
and what it contains, and puts all of that into a **CodeSymbol** — one symbol per meaningful language construct.
---

## Section 3 — Building the embedding input

Now, having knowledge about **CodeSymbols**, we can build the input for a vector database. In **semcode**
[Qdrant](https://qdrant.tech/) is used for to store vectors we have two types of inputs: dense and sparse.

What are dense embeddings?

**Dense embeddings** encode the *meaning* of text into a fixed-size vector of floating-point numbers — typically
hundreds or thousands of dimensions depending on which embedding provider is chosen. Two pieces of text that express the
same idea will land close together in that vector space even if they share no words in common. For code search this
means a query like "find the method that handles payment retries" can surface `retryWithBackoff()`
without those words appearing anywhere in the source.

```shell
dense = [0.2, 0.3, 0.5, 0.7, ...]  # several hundred floats
```

What are sparse embeddings?

**Sparse embeddings** work the opposite way: instead of capturing meaning, they represent text as a large vocabulary
vector where almost every entry is zero and only the terms that actually appear get a non-zero weight. BM25 is the
algorithm behind this — it scores each token by how often it appears in a document relative to how common it
is across the whole corpus. This makes sparse embeddings excellent at exact keyword matching: if you search for
`PlaceOrderRequest` or `@Transactional`, BM25 will find every document that contains those tokens precisely.

```shell
# Taken from Qdrant docs
sparse = [{331: 0.5}, {14136: 0.7}]  # 20 key value pairs
# The numbers 331 and 14136 map to specific tokens in the vocabulary e.g. ['Transactional', 'PlaceOrderRequest'].
# The rest of the values are zero. This is why it’s called a sparse vector.
```

How does **semcode** build the dense input?

The whole `CodeSymbol` object is not embedded directly — it is first serialized into a single text string, and that
string is what the embedding model sees. One symbol produces one string, which produces one vector: an array of
floating-point numbers (e.g. 768 or 3072 floats depending on the provider). The `CodeSymbol` fields that carry
*meaning* go into that string.
It starts with a human-readable preamble that names the language, symbol type, parent class, and owning service, then
layers in framework-specific metadata — Spring stereotypes, HTTP method and route, annotations — followed by a truncated
docstring and the full signature. Finally, the raw source body is appended, capped at ~6,000 characters (~1,500
tokens). The goal is to give the embedding model everything it would need to understand the symbol's role, not just
its implementation.
The fields that are useful for *displaying or filtering* results (like `start_line`,
`file_path`, or `parent_name`, `package`) are stored separately as the Qdrant **payload** — they sit next to the vector
but are never embedded.

How does **semcode** build the sparse input?

Building BM25 text input is minimal — it concatenates only the signature, docstring, and raw source, with no metadata.
It splits camelCase and snake_case identifiers into their component words while keeping the original form alongside. A
token like `PlaceOrderRequest` becomes `Place Order Request` — so BM25 can match the exact identifier *and* a
natural-language query like "place order request" that doesn't use the original casing.

Why does sparse matter when the dense input is already rich? Dense embeddings excel at intent — a query like "find
the method that retries payments" can surface `retryWithBackoff` even if no query word appears in the source — but that
power trades precision for meaning, and rare or project-specific identifiers like `PlaceOrderRequest` get smoothed
toward neighboring concepts in the model's vector space. BM25 fills exactly that gap: it matches tokens literally with
no compression, and **semcode's** code-aware tokenization splits `PlaceOrderRequest` into `Place Order Request` alongside
the original, so it handles both exact identifier lookups and natural-language queries that dense alone would miss.

So the full picture is:
Every `CodeSymbol` produces two inputs. The dense input is wide and context-rich — it tells the model the symbol's
place in the system. The sparse input is narrow and literal — it gives BM25 the exact tokens to match against. Both
are computed in the same pipeline step and stored together as a single point in Qdrant.

---

## Section 4 — What goes into Qdrant: the named-vector schema

- One collection (`code_symbols`) with **two named vectors per point**:
    - `text-dense` — cosine, provider-dependent dims
    - `text-sparse` — Qdrant native BM25 sparse index
    - Reference: `server/store/qdrant.py:47-62`
- The payload (the underappreciated half of every vector DB):
    - Identity: `symbol_name`, `symbol_type`, `language`, `service`, `file_path`, `package`, `parent_name`
    - Display: `signature`, `source`, `docstring`, `start_line`, `end_line`
    - Filtering: `annotations`, `chunk_tier`, framework `extras` (HTTP method, route, Spring stereotype)
    - Bookkeeping: `file_hash` (for incremental reindex), `indexed_at`
    - Reference: `server/indexer/pipeline.py:104-125`
- Keyword payload indexes on the high-cardinality filter fields → fast `language=python AND service=catalog` style
  filters
- Separate `git_commits` collection — dense-only, message + diff metadata

---

## Section 5 — Hybrid retrieval at query time (RRF in one Qdrant call)

- The query goes through *both* encoders: dense (full model) and sparse (tokenizer + BM25)
- One Qdrant `query_points` call does the fusion server-side:
  ```
  FusionQuery(fusion=Fusion.RRF),
  prefetch=[
      Prefetch(query=dense_vec, using="text-dense", limit=K*2),
      Prefetch(query=sparse_vec, using="text-sparse", limit=K*2),
  ]
  ```
    - Reference: `server/store/qdrant.py:203-223`
- How RRF works in one paragraph: each retriever returns a ranked list, RRF scores each doc by `Σ 1/(k + rank_i)`, ties
  broken by combined rank. No tuning of weights needed.
- Why this beats weighted sum: scale-free, doesn't depend on score calibration between dense cosine and BM25
- Reference: `server/tools/search.py:20-78`

---

## Section 6 — Indexing flow: incremental, content-addressed

- Walk the repo (GitHub API or local), apply excludes
- For each file: compute blob SHA → compare against payload's `file_hash` → skip if unchanged
- Parse → build dense + sparse inputs → batch-embed → upsert (delete-then-insert per file path)
- Cleanup pass removes stale symbols for files no longer in the repo
- Reference: `server/indexer/pipeline.py:128-249`
- Why this matters: embedding API costs amortize across reindexes; large monorepos stay tractable

---

## Section 7 — Bonus: indexing git history as a second RAG corpus

- Separate pipeline embeds **commit messages + file deltas** into the `git_commits` collection
- Dense-only (commit messages are short, sparse adds little)
- Enables "when was retry logic introduced?" style queries
- Reference: `server/indexer/git_history.py:24-63`, `server/tools/history.py`

---

## Section 8 — What I'd do differently / open questions

- Re-ranker on top of RRF (cross-encoder) — worth the latency?
- Per-language collections vs single collection — when does the trade-off flip?
- Embedding the *call graph* (cross-symbol relationships), not just symbols in isolation
- Tuning the 6000-char source cap per language

---

## Section 9 — Takeaways

- Symbol-level chunking + rich, language-aware embedding inputs are the foundation
- Hybrid dense+sparse with RRF gives you both "intent" and "exact name" search for free, server-side
- The payload is half the system — invest in it
- Incremental indexing via blob SHAs is what makes this affordable at repo scale

---

## Appendix — Suggested diagrams

1. Pipeline overview: file → Tree-sitter → `CodeSymbol` → dense input + sparse input → Qdrant
2. Qdrant point anatomy: two named vectors + payload fields, annotated
3. Query-time RRF: query → two encoders → two ranked lists → fused result

## Reference

https://qdrant.tech/articles/sparse-vectors/
