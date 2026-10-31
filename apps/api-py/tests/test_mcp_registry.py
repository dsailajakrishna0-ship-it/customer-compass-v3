"""Choosing between the MCP servers: defaults, configuration, and what the API reports."""

import pytest
from fastapi import HTTPException

from app.mcp import registry
from app.routes import chat
from app.routes import mcp as mcp_route


def test_the_default_is_fastmcp_and_springboot_is_off_until_configured():
    known = registry.backends()
    assert known["fastmcp"].configured and not known["springboot"].configured
    assert registry.resolve().id == "fastmcp"


def test_a_request_can_choose_a_configured_backend(monkeypatch):
    monkeypatch.setenv("MCP_SPRINGBOOT_URL", "http://mcp-spring:8003/mcp")
    assert registry.resolve("springboot").url == "http://mcp-spring:8003/mcp"


def test_the_default_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("MCP_SPRINGBOOT_URL", "http://mcp-spring:8003/mcp")
    monkeypatch.setenv("MCP_BACKEND", "springboot")
    assert registry.resolve().id == "springboot"


def test_an_unconfigured_backend_is_refused_with_the_setting_to_change():
    with pytest.raises(registry.UnknownBackendError, match="MCP_SPRINGBOOT_URL"):
        registry.resolve("springboot")


def test_an_unknown_backend_is_refused_and_the_choices_are_listed():
    with pytest.raises(registry.UnknownBackendError, match="fastmcp, springboot"):
        registry.resolve("rest")


def test_a_wrong_default_stops_start_up(monkeypatch):
    monkeypatch.setenv("MCP_BACKEND", "rest")
    with pytest.raises(Exception, match="mcp_backend"):
        registry.resolve()


@pytest.mark.asyncio
async def test_the_tools_route_answers_400_for_a_backend_that_is_not_configured():
    request = chat.ToolsChatRequest(
        messages=[{"role": "user", "content": "hi"}], mcpServer="springboot"
    )
    with pytest.raises(HTTPException) as exc:
        await chat.tools_chat(request)
    assert exc.value.status_code == 400 and "MCP_SPRINGBOOT_URL" in exc.value.detail


@pytest.mark.asyncio
async def test_the_servers_endpoint_reports_configured_and_reachable(monkeypatch):
    async def probe(backend):
        return backend.id == "fastmcp"

    monkeypatch.setattr(mcp_route, "_reachable", probe)
    body = await mcp_route.servers()
    assert body["default"] == "fastmcp"
    assert body["servers"] == [
        {"id": "fastmcp", "label": "FastMCP (Python)", "configured": True, "reachable": True},
        {
            "id": "springboot",
            "label": "Spring Boot (Java)",
            "configured": False,
            "reachable": False,
        },
    ]


@pytest.mark.asyncio
async def test_an_unconfigured_backend_is_never_probed():
    assert await mcp_route._reachable(registry.backends()["springboot"]) is False


def test_the_chat_request_accepts_the_camel_case_field_the_web_app_sends():
    request = chat.ToolsChatRequest.model_validate(
        {"messages": [{"role": "user", "content": "hi"}], "mcpServer": "fastmcp"}
    )
    assert request.mcp_server == "fastmcp"
