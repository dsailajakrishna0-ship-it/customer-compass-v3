"""Stage 9 MCP server: exposes the 4 tool functions over MCP via stdio.

Run standalone as `python -m app.mcp.server` -- the chat route's tool-call
loop spawns exactly this as a subprocess (see client.py), per the Stage 9
design decision to run the MCP server as a separate process rather than
in-process.
"""

import asyncio

from mcp.server.mcpserver import MCPServer

from app.mcp.tools import (
    create_followup_task_tool,
    get_company_summary_tool,
    get_open_deals_tool,
    search_documents_tool,
)

# MCP server: exposes CRM tools to the model over stdio
server = MCPServer(name="customer-compass-tools")


@server.tool()
async def get_company_summary(company_name: str) -> dict:
    """Get verified CRM facts for a company: industry, relationship status,
    open deals, and won/lost deal counts."""
    return await get_company_summary_tool(company_name)


@server.tool()
async def get_open_deals(company_name: str) -> dict:
    """Get only the open deals for a company (name, amount, status, expected
    close date)."""
    return await get_open_deals_tool(company_name)


@server.tool()
async def search_documents(query: str, company_name: str | None = None) -> dict:
    """Search CRM interaction documents (emails, calls, support tickets,
    meeting notes) semantically. Optionally scope to one company."""
    return await search_documents_tool(query, company_name)


@server.tool()
async def create_followup_task(company_name: str, note: str, confirm: bool = False) -> dict:
    """Propose (confirm=false, the default) or create (confirm=true) a
    follow-up task for a company. Only pass confirm=true after the user has
    explicitly confirmed the proposed task in their latest message."""
    return await create_followup_task_tool(company_name, note, confirm)


if __name__ == "__main__":
    asyncio.run(server.run_stdio_async())
