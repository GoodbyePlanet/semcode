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
The fields that are useful for *displaying* results (like `start_line`, `end_line`, `file_path`, `signature`, `source`)
or *filtering* them (like `language`, `service`, `symbol_type`) are stored separately as the Qdrant **payload** —
they sit next to the vector but are never embedded.

How does **semcode** build the sparse input?

Building BM25 text input is minimal — it concatenates only the signature, docstring, and raw source, with no metadata.
It splits camelCase and snake_case identifiers into their component words while keeping the original form alongside. A
token like `PlaceOrderRequest` becomes `Place Order Request` — so BM25 can match the exact identifier *and* a
natural-language query like "place order request" that doesn't use the original casing.

Why does sparse matter when the dense input is already rich? Dense embeddings excel at intent — a query like "find
the method that retries payments" can surface `retryWithBackoff` even if no query word appears in the source — but that
power trades precision for meaning, and rare or project-specific identifiers like `PlaceOrderRequest` get smoothed
toward neighboring concepts in the model's vector space. BM25 fills exactly that gap: it matches tokens literally with
no compression, and **semcode's** code-aware tokenization splits `PlaceOrderRequest` into `Place Order Request`
alongside
the original, so it handles both exact identifier lookups and natural-language queries that dense alone would miss.

So the full picture is:
Every `CodeSymbol` produces two inputs. The dense input is wide and context-rich — it tells the model the symbol's
place in the system. The sparse input is narrow and literal — it gives BM25 the exact tokens to match against. Both
are computed in the same pipeline step and stored together as a single point in Qdrant.

---

## Section 4 — What goes into Qdrant: the named-vector schema

In Section 3 it's explained that we have two inputs per symbol — dense and sparse — stored together in Qdrant.
This section explains *how* they are stored: the shape of a single stored point and why that shape matters at query
time.

### Named vectors: two vectors, one point

Qdrant lets a single point carry multiple vectors under distinct names, each with its own distance metric and index.
**semcode** uses this directly: the `code_symbols` collection defines two named vectors per point.

- `text-dense` — cosine distance, dimensionality set by the embedding provider.
- `text-sparse` — Qdrant's native BM25 sparse index.

The advantage of named vectors over two parallel collections is that one point ID identifies one symbol everywhere.
Dense and sparse retrievers always agree on what "document 42" means, which is what makes server-side fusion (next
section) possible in a single round-trip.

### Anatomy of a stored point

Alongside the two vectors, there is the payload — the non-embedded half of the point.
Payload is a JSON object with the following fields:

- **Identity & filtering** — `symbol_name`, `symbol_type`, `language`, `service`,
  `file_path`, `package`, `parent_name`. These uniquely place the symbol in
  the repo, and three of them — `language`, `service`, `symbol_type` — are
  wired as active query-time filters.
- **Display** — `signature`, `source`, `docstring`, `start_line`, `end_line`,
  `annotations`, `extras` (HTTP method, route, Spring stereotype). These are
  what the MCP client renders back to the user — they are never filtered on,
  just returned alongside the score (`server/tools/search.py:60-71`).
- **Bookkeeping** — `file_hash`, `indexed_at`. Not exposed at query time, but
  critical for the incremental reindex flow: the hash is how the pipeline
  decides a file hasn't changed and can be skipped (`server/indexer/pipeline.py:122-123`).

### Payload indexes: filters before vectors

By default, when you search Qdrant, it scores vectors first and filters results afterward. That means if you ask for
"OAuth 2.0 implementation in payment-service", Qdrant would still compare your query vector against *every* stored
symbol — then throw away the ones that don't match.

Payload indexes flip this order. **semcode** indexes six fields — `language`, `service`, `symbol_type`, `chunk_tier`,
`parent_name`, `file_path` — so Qdrant can narrow the candidate set *before* any vector math happens. The
vector search then runs only over the matching symbols, not the whole collection.

### A second, simpler collection

Code symbols aren't the only RAG corpus in **semcode**. A separate `git_commits` collection stores commit messages and
diff metadata as dense-only points.

---

## Section 5 — Indexing flow: incremental, content-addressed

Embedding API calls are the dominant cost in any indexing run, and re-embedding an entire repository on every push would
be expensive at scale. **semcode** avoids this by treating indexing as a diff operation: it uses git blob
SHAs as content fingerprints to identify which files have changed, and only those files are parsed, embedded, and
upserted. A service with 1,000 files where 10 changed sends 10 embedding requests, not 1,000. This section describes
the full indexing pipeline.

### Step 1 — Discovery via the Git Trees API

The pipeline opens by calling GitHub's Trees API. One request returns every file in the repository tree. Crucially,
each entry already includes the git `blob_sha` — git's own content hash for that file
— without downloading a single byte of source code.

### Step 2 — Hash comparison before any network I/O

Before fetching any file content, the pipeline loads the `file_hash` values stored in the Qdrant payload for all
already-indexed symbols in this service. It then compares each file's `blob_sha`
against that map. If the hashes match, the file is skipped entirely — no HTTP download, no parsing, no embedding call.
This is the core of the incremental design — instead of re-embedding every symbol on every run, only files whose content
actually changed are embedded again.

### Step 3 — Fetch, parse, embed, upsert

For every file that is new or has a changed blob SHA, the pipeline fetches the content by SHA,
parses it into `CodeSymbol` objects, builds both dense and sparse inputs as described in Section 3,
and calls both embedding providers in a batch.

The upsert is a **delete-then-insert at the file level**: all existing points whose `file_path` matches are removed
first, then the freshly embedded points are inserted. This keeps the index clean when a file loses methods,
gains new ones, or is restructured.

### Step 4 — Cleanup pass for deleted files

After the main loop, the pipeline diffs the current repo file set against every `file_path` that exists in Qdrant.
Any path no longer present in the repo is deleted.

---

## Section 6 — Hybrid retrieval at query time

At query time, the same two-track split like in the ingestion phase runs in reverse. The query string goes through both
encoders — the dense model turns it into a floating-point vector, the BM25 turns it into a sparse vector.
Both are sent to Qdrant in a single call, which runs each retriever independently, ranks the top K×2 candidates
from each, and produces two separate ranked lists.

Qdrant then uses **Reciprocal Rank Fusion (RRF)** to merge those two ranked lists into one before returning the
final top K results. For example, using the query _"find the method that retries failed payments"_ merge looks like this:

1. Dense retriever returns its ranked list:
   `[retryWithBackoff (rank 1), processPayment (rank 2), PlaceOrderRequest (rank 3), ...]`
2. Sparse retriever returns its ranked list:
   `[PlaceOrderRequest (rank 1), retryWithBackoff (rank 2), handleTimeout (rank 3), ...]`
3. RRF scores each result with `1 / (k + rank)` from every list it appears in, then sums those contributions
4. Everything is re-sorted by that combined score → one final list:
   `[retryWithBackoff, PlaceOrderRequest, processPayment, handleTimeout, ...]`

`retryWithBackoff` ranked first in dense and second in sparse — both retrievers agreed, so it floats to the top.
`PlaceOrderRequest` ranked first in sparse (exact token match) but third in dense — it still surfaces near the top
because the sparse retriever was confident. `processPayment` only appeared in one list despite a good dense rank,
so it scores lower.

RRF rewards consistent rank across retrievers. The score it produces answers a simpler question:
"how consistently did this result appear near the top across both dense and sparse retrievers?"
---

## Section 7 — Takeaways

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
https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion