#!/usr/bin/env python3
"""Calls one tool on a running MCP tool server and prints the answer: a way to try a server without a model.

    uv run --project apps/api-py python contracts/call_tool.py http://localhost:8002/mcp get_open_deals '{"company_name": "Acme"}'
    uv run --project apps/api-py python contracts/call_tool.py http://localhost:8003/mcp get_open_deals '{"company_name": "Acme"}'

With no tool name it lists the server's tools. Note that create_followup_task with "confirm": true really
writes a task.
"""

from __future__ import annotations

import asyncio
import json
import sys


async def run(url: str, tool: str | None, arguments: dict) -> int:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            if tool is None:
                for t in (await session.list_tools()).tools:
                    print(f"{t.name}: {json.dumps(t.input_schema.get('properties', {}))}")
                return 0
            reply = await session.call_tool(tool, arguments)
            text = "\n".join(b.text for b in reply.content if hasattr(b, "text"))
            try:
                text = json.dumps(json.loads(text), indent=2)
            except json.JSONDecodeError:
                pass
            print(text)
            return 1 if reply.is_error else 0


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3, 4):
        print(__doc__)
        return 2
    arguments = json.loads(argv[3]) if len(argv) == 4 else {}
    return asyncio.run(run(argv[1], (argv[2] if len(argv) > 2 else "") or None, arguments))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
