from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from server.tools.search import file_content_cache


@pytest.fixture(autouse=True)
def clear_file_content_cache():
    """The get_code_context content cache is process-wide — keep tests isolated."""
    file_content_cache.clear()
    yield
    file_content_cache.clear()


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
