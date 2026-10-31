"""The FastMCP server over real HTTP: start it on a local port and talk to it with the real client.

Only the tool bodies are replaced (they need Postgres and Qdrant); the protocol, the transport and
the client are the real ones."""

import asyncio
import socket

import pytest
import pytest_asyncio

from app.mcp import client, server
from app.mcp.schemas import TOOL_ARGS


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest_asyncio.fixture
async def running_server(monkeypatch):
    """The FastMCP server listening on a free local port, and the client pointed at it."""
    port = free_port()
    monkeypatch.setenv("MCP_FASTMCP_URL", f"http://127.0.0.1:{port}/mcp")
    monkeypatch.setenv("MCP_BACKEND", "fastmcp")
    task = asyncio.create_task(server.server.run_streamable_http_async(host="127.0.0.1", port=port))
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            await asyncio.sleep(0.05)
    else:
        task.cancel()
        pytest.fail("the MCP server did not start listening")
    yield port
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_the_client_discovers_the_four_tools_over_http(running_server):
    async with client.mcp_session() as session:
        specs = await client.list_tool_specs(session)
    assert {s.name for s in specs} == set(TOOL_ARGS)
    assert all(s.description and s.input_schema["type"] == "object" for s in specs)


@pytest.mark.asyncio
async def test_a_tool_call_travels_over_http_and_returns_the_tool_result(
    running_server, monkeypatch
):
    seen = {}

    async def fake(company_name):
        seen["company_name"] = company_name
        return {"status": "executed", "company": {"name": "Acme Fabrication"}}

    monkeypatch.setattr(server, "get_open_deals_tool", fake)
    async with client.mcp_session() as session:
        text = await client.call_tool(session, "get_open_deals", {"company_name": "Acme"})
    assert seen == {"company_name": "Acme"}
    assert '"Acme Fabrication"' in text


@pytest.mark.asyncio
async def test_an_unreachable_server_is_an_error_not_a_hang(monkeypatch):
    monkeypatch.setenv("MCP_FASTMCP_URL", f"http://127.0.0.1:{free_port()}/mcp")
    with pytest.raises(Exception):  # noqa: B017 - the exact type belongs to the HTTP library
        async with asyncio.timeout(5):
            async with client.mcp_session():
                pass


@pytest.mark.asyncio
async def test_a_foreign_host_header_is_refused(running_server):
    """DNS-rebinding protection: the server only answers the Host headers in MCP_ALLOWED_HOSTS."""
    import httpx

    async with httpx.AsyncClient() as http:
        reply = await http.post(
            f"http://127.0.0.1:{running_server}/mcp",
            headers={"Host": "evil.example", "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
    assert reply.status_code in (400, 403, 421)
