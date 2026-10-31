# 0015 — MCP over HTTP, with two interchangeable tool servers

- **Status:** Accepted
- **Date:** 2026-10-31
- **Roadmap sub-stage:** 2.2a (Python, this record) and 2.2b (Spring Boot)

## Context

Until now every `/chat/tools` request started a new Python subprocess, talked to it over standard input and output (MCP "stdio"), and threw it away. That costs a process start per question, cannot be shared, observed or scaled on its own, and keeps the tool server inside the API's lifecycle.

The project owner also wants to learn Spring Boot (Java) next to Python, and the roadmap's fit analysis put an MCP server at medium-high for Spring. So the tools should be reachable as a *service*, and there should be two implementations that can be compared and swapped.

## Decision

1. **MCP over streamable HTTP, long-lived.** The FastMCP server (`apps/api-py/app/mcp/server.py`, the official `mcp` SDK's `MCPServer`) runs as its own Compose service, `mcp-fastmcp`, on port 8002 at `/mcp`. It uses the API's image with a different command, because its tools call the same CRM and retrieval code as the API. The API's client opens an HTTP session per chat request; the stdio subprocess path is removed.
2. **Two backends, one contract.** The ids are `fastmcp` and `springboot`. The default is `MCP_BACKEND` (default `fastmcp`); each backend has a URL setting (`MCP_FASTMCP_URL`, `MCP_SPRINGBOOT_URL`); a backend with no URL is "not configured" and cannot be chosen (a clear `400` names the setting). A chat request may name a backend with `mcpServer`, and the web app offers radio buttons (`GET /api/v1/mcp/servers` lists them with a reachability probe).
3. **`contracts/mcp-tools.json` is the shared contract**, at the repository root because it belongs to neither server. It lists the tools (argument names, types, required fields) and a few read-only calls with their expected answers on the demo data. `contracts/check_server.py` checks any running server against it. CI runs it against the FastMCP container; a test keeps the in-process FastMCP definitions equal to it; the Spring server (2.2b) must pass the same check.
4. **Layout and names.** The Java server will live in `services/mcp-java` (own build, Dockerfile and CI job; no shared code). Names carry the technology: Compose services `mcp-fastmcp` and `mcp-spring`, ids `fastmcp` and `springboot`. The FastMCP code stays under `apps/api-py/app/mcp/` because moving it would copy shared code.
5. **The model never sees which server it is talking to.** Tool definitions come from the Pydantic models of [ADR 0014](0014-native-tool-calling.md), not from the server, so both servers give the model exactly the same tools, and `confirm` is still never offered.
6. **Host allowlist.** The server accepts only the Host headers in `MCP_ALLOWED_HOSTS` (`localhost`, `127.0.0.1`, `mcp-fastmcp`), the SDK's protection against DNS rebinding; an unknown host gets `421`.

## Alternatives considered

- **Keep stdio:** simplest, but one process per question and no second implementation to compare.
- **Run the MCP server inside the API process:** no extra container, but then it is not an independent service and a Java twin could not be swapped in.
- **Make the Spring server the only server:** drops the Python path that shares code with the API; the point here is to have both.
- **A separate repository for the Java server:** considered and deferred; a folder with its own build gives the same independence ([ADR 0013](0013-conflict-bot.md) records the tooling for stacked changes; this choice was made in conversation with the owner).

## Consequences

- **One more container**, and the API now waits for `mcp-fastmcp` to be healthy.
- **Not verified:** a real chat turn through the tool servers, because no OpenRouter key was available. What was verified: the container passes the contract (the same check CI runs), the API reaches it by its Compose name, the Host allowlist, and a request for an unconfigured backend. The tool-call evaluation (exit criterion: accuracy at least the baseline) must be re-taken with a key.
- **The contract is data, not a type:** both servers can drift in ways it does not test (it checks four calls). Extend it when a tool gains behaviour.
- **Session per request:** each chat turn opens and closes an MCP session over HTTP. Cheap, but a connection pool would be the next step if latency shows up.
