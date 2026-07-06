from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mcp.server.fastmcp import FastMCP


def get_tool(register: Callable[[FastMCP], None], name: str) -> Callable:
    """Register a tool module against a throwaway FastMCP instance and return
    the underlying async function, bypassing MCP's request/response plumbing."""
    mcp = FastMCP("test")
    register(mcp)
    return mcp._tool_manager._tools[name].fn


@dataclass
class StubHit:
    payload: dict[str, Any] = field(default_factory=dict)
    score: float = 1.0
