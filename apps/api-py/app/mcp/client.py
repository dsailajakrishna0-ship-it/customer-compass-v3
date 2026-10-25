"""Stage 9 MCP client: spawns app/mcp/server.py as a stdio subprocess,
discovers its tools, and invokes them. Used by the chat route's tool-calling
loop (app/routes/chat.py).
"""

import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict


# MCP client: launches the tool server as a subprocess and talks to it over stdio
def _server_params() -> StdioServerParameters:
    # Use sys.executable (the exact interpreter running this process, inside
    # the uv-managed venv) rather than a bare "python3" -- guarantees the
    # subprocess has the `mcp` package installed regardless of PATH.
    #
    # MCP's StdioServerParameters defaults to a minimal env allowlist (PATH,
    # HOME, etc.) for subprocess security -- it does NOT inherit secrets like
    # GOOGLE_API_KEY/DATABASE_URL/OLLAMA_URL/OPENROUTER_API_KEY. The tool
    # server needs those (it calls the same crm/rag modules the API does),
    # so we explicitly pass through the parent process's full environment.
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp.server"],
        env=dict(os.environ),
    )


@asynccontextmanager
async def mcp_session():
    """Async context manager yielding an initialized ClientSession connected
    to a freshly spawned app.mcp.server subprocess."""
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
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
