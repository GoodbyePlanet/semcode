from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mcp.server.mcpserver import MCPServer


def get_tool(register: Callable[[MCPServer], None], name: str) -> Callable:
    """Register a tool module against a throwaway MCPServer instance and return
    the underlying async function, bypassing MCP's request/response plumbing."""
    mcp = MCPServer("test")
    register(mcp)
    return mcp._tool_manager._tools[name].fn


@dataclass
class StubHit:
    payload: dict[str, Any] = field(default_factory=dict)
    score: float = 1.0
