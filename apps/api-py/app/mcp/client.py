"""MCP client: connects to a tool server over streamable HTTP, discovers its tools, calls them.

Used by the chat route's tool-calling loop (app/routes/chat.py). Which server is decided by
app/mcp/registry.py; both implement the same tools. The server is a long-running service (Stage 2.2);
before that this module started a new stdio subprocess for every chat turn.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.mcp.registry import resolve


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@asynccontextmanager
async def mcp_session(backend: str | None = None):
    """An initialized ClientSession connected to the chosen MCP server (default: MCP_BACKEND)."""
    url = resolve(backend).url
    assert url is not None  # resolve() only returns configured backends
    async with streamable_http_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            yield session


async def list_tool_specs(session: ClientSession) -> list[ToolSpec]:
    result = await session.list_tools()
    return [
        ToolSpec(name=t.name, description=t.description or "", input_schema=t.input_schema)
        for t in result.tools
    ]


async def call_tool(session: ClientSession, name: str, arguments: dict) -> str:
    """Calls a tool and returns its result as a text string (the tool
    functions return JSON-serializable dicts; MCP wraps that as TextContent)."""
    result = await session.call_tool(name, arguments)
    parts = [block.text for block in result.content if hasattr(block, "text")]
    return "\n".join(parts)
