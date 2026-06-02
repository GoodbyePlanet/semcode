---
paths:
  - "server/routes/**/*.py"
  - "server/tools/**/*.py"
---

# FastMCP + Starlette HTTP conventions

This project uses **FastMCP**. HTTP routes are registered on the
`FastMCP` instance via `@mcp.custom_route`. Never add routes to a separate
FastAPI or Starlette app.

## Route registration pattern

Wrap registration in a `register_*` function that accepts `mcp: FastMCP`. Call it
from `server/main.py`:

```python
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import StreamingResponse

def register_http_routes(mcp: FastMCP) -> None:

    @mcp.custom_route("/reindex", methods=["POST"])
    async def reindex(request: Request) -> StreamingResponse:
        ...
```

Same pattern for MCP tools — `register_*_tools(mcp: FastMCP)` in `server/tools/`.

## Request body parsing

Never assume a body exists. Check `content-type` first:

```python
body: dict = {}
if request.headers.get("content-type", "").startswith("application/json"):
    raw = await request.body()
    if raw:
        body = json.loads(raw)
```

## Streaming responses (NDJSON)

All indexing endpoints return `StreamingResponse` with
`media_type="application/x-ndjson"`. Emit one JSON object per line:

- Progress frames: `{"type": "progress", "phase": "...", "current": int, "total": int, "percentage": float, "service": str}`
- Done frame: `{"type": "done", "result": {...}}`
- Error frame: `{"type": "error", "message": str}`

Use an `asyncio.Queue` + `asyncio.create_task` to decouple the async pipeline
from the generator that yields to the client:

```python
async def generate():
    queue: asyncio.Queue = asyncio.Queue()

    async def run() -> None:
        try:
            result = await pipeline.index_all(progress_callback=lambda e: queue.put_nowait(e))
            await queue.put({"__done__": True, "result": result})
        except Exception as exc:
            await queue.put(exc)

    task = asyncio.create_task(run())
    try:
        while True:
            item = await queue.get()
            if isinstance(item, Exception):
                yield json.dumps({"type": "error", "message": str(item)}) + "\n"
                break
            if isinstance(item, dict):
                yield json.dumps({"type": "done", "result": item["result"]}) + "\n"
                break
            yield json.dumps({"type": "progress", **dataclasses.asdict(item)}) + "\n"
    finally:
        await task

return StreamingResponse(generate(), media_type="application/x-ndjson")
```

## Logging in routes

Log at entry with `%s` args (not f-strings):

```python
logger.info("Reindex started: service=%s force=%s", service or "ALL", force)
```

## MCP tool conventions

- Tool functions registered with `@mcp.tool()` must have descriptive docstrings —
  these become the tool description visible to AI clients.
- Access shared state via `server/state.py` getters (`get_store()`, `get_commit_store()`)
  rather than importing globals directly.
- Tool implementations live in `server/tools/`; route implementations in `server/routes/`.
