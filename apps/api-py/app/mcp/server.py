"""The FastMCP tool server: the four CRM tools over streamable HTTP (MCP, Stage 2.2).

Run as its own long-lived service: `python -m app.mcp.server` (the `mcp-fastmcp` container). The tool
bodies live in app/mcp/tools.py and call the same CRM and retrieval code as the API. A second server
with the same tools, in Java, lives in services/mcp-java; contracts/mcp-tools.json says what both must do.
"""

import asyncio

from mcp.server.mcpserver import MCPServer

from app.mcp.tools import (
    create_followup_task_tool,
    get_company_summary_tool,
    get_open_deals_tool,
    search_documents_tool,
)

# MCP server: exposes CRM tools to the model over streamable HTTP
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


def main() -> None:
    from mcp.server.transport_security import TransportSecuritySettings

    from app.config import get_settings
    from app.logs import configure_logging

    configure_logging()
    settings = get_settings()
    asyncio.run(
        server.run_streamable_http_async(
            host=settings.mcp_server_host,
            port=settings.mcp_server_port,
            # only these Host headers are accepted (protects a local server from DNS rebinding)
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[
                    h.strip() for h in settings.mcp_allowed_hosts.split(",") if h.strip()
                ],
            ),
        )
    )


if __name__ == "__main__":
    main()
