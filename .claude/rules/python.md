---
paths:
  - "**/*.py"
---

# Python conventions

## Module header

Every module must start with `from __future__ import annotations`. This enables
PEP 563 deferred evaluation — it allows forward references in type hints without
quotes and is already the project-wide convention.

## Type hints

- Annotate every function: parameters and return type. No untyped public functions.
- Python ≥ 3.12 is required — use `X | Y` union syntax, not `Optional[X]` or `Union[X, Y]`.
- Use built-in generics: `list[str]`, `dict[str, int]`, not `List[str]` / `Dict`.
- Use `Protocol` for structural (duck) typing instead of abstract base classes:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
```

## Logging

Never use `print()`. Use `logging.getLogger(__name__)` and pass format args as
separate arguments (defers string formatting to when the log is actually emitted):

```python
# Correct
logger = logging.getLogger(__name__)
logger.info("Indexing service=%s force=%s", service, force)

# Wrong — eager formatting, print
print(f"indexing {service}")
logger.info(f"Indexing service={service}")
```

## Naming

- Functions and variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private helpers: prefix with `_` (e.g. `_build_bm25_text`)

## String formatting

Use f-strings everywhere except logger calls (see above).

## Dependency management

Use `uv`, not `pip`:

- Install deps: `uv sync` / `uv sync --group dev`
- Run tools: `uv run pytest`, `uv run <script>`
- Never call `pip install` or `python -m pytest` directly.

## Comprehensions over accumulate-in-loop

Prefer list comprehensions. Refactor collect-and-append patterns:

```python
# Wrong
results = []
for sym in symbols:
    if sym.language == "python":
        results.append(sym.name)

# Correct
results = [sym.name for sym in symbols if sym.language == "python"]
```

Use generators for large sequences to avoid materializing the whole list at once.
