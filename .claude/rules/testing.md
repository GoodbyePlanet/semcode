---
paths:
  - "tests/**/*.py"
---

# Testing conventions

## Framework

Use `pytest`. `asyncio_mode = "auto"` is set globally in `pyproject.toml` — write
`async def test_...()` directly. Never add `@pytest.mark.asyncio`.

## File header

Every test file starts with `from __future__ import annotations`.

## Test naming

Flat functions, not classes. Name tests after the behaviour being verified:

```python
# Correct — describes what the code does
def test_empty_file_returns_no_symbols(): ...
def test_async_function_detected_as_async(): ...

# Wrong — generic or vague
def test_parser(): ...
def test_it_works(): ...
```

## Fixtures

- Use `@pytest.fixture` for reusable setup — they compose cleanly and handle teardown.
- Default scope is function. Use `scope="session"` only for expensive, read-only
  resources (e.g. `fixtures_dir` in `conftest.py`).
- Prefer `conftest.py` for fixtures shared across multiple test files.

## Mocking

Use `unittest.mock` — `AsyncMock`, `MagicMock`, `patch`. Do **not** use `pytest-mock`.

```python
from unittest.mock import ANY, AsyncMock, MagicMock, patch

@pytest.fixture
def mock_pipeline():
    pipeline = AsyncMock()
    pipeline.index_service.return_value = {"files": 10, "chunks": 50, "skipped": 2}
    return pipeline

async def test_reindex(client, mock_pipeline):
    with patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline):
        resp = await client.post("/reindex")
    assert resp.status_code == 200
```

Use `patch` as a context manager, not a decorator, when patching multiple targets.

## HTTP endpoint tests

Use `httpx.AsyncClient` with `httpx.ASGITransport` — never spin up a real server:

```python
@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
```

Use `respx` for mocking outbound `httpx` calls (external HTTP the server makes).

## Parser tests

Parse fixtures, then assert by building a name-keyed dict. Check `symbol_type`,
`extras`, and `language` explicitly:

```python
def test_canonical_api_fixture(read_fixture):
    src = read_fixture("python/api.py")
    syms = PythonParser().parse_file(src, "svc/api.py")

    by_name = {s.name: s for s in syms}
    assert set(by_name) == {"ChatRequest", "chat", "helper"}

    chat = by_name["chat"]
    assert chat.symbol_type == "api_route"
    assert chat.extras["http_method"] == "POST"
```

Add canonical fixture files under `tests/fixtures/<language>/` for each new language
parser, then snapshot-test via the `read_fixture` fixture from `conftest.py`.

## Parametrize

Use `@pytest.mark.parametrize` for data-driven cases — it avoids duplicating test
logic and makes failures easy to pinpoint:

```python
@pytest.mark.parametrize("source,expected_type", [
    (b"def fn(): pass", "function"),
    (b"async def fn(): pass", "function"),
    (b"class Foo: pass", "class"),
])
def test_symbol_type(source, expected_type):
    syms = PythonParser().parse_file(source, "mod.py")
    assert syms[0].symbol_type == expected_type
```
