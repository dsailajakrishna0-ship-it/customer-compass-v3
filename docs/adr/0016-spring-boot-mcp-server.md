# 0016 — The Spring Boot MCP server

- **Status:** Accepted
- **Date:** 2026-10-31
- **Roadmap sub-stage:** 2.2b

## Context

[ADR 0015](0015-mcp-over-http-two-servers.md) made the tool server a service with a contract and a configurable choice of implementation. The project owner wants to learn Spring Boot beside Python, and an MCP server is a small, well-bounded first Java module: four tools, one contract, no UI.

## Decision

- **A Java twin of the four tools** in `services/mcp-java`: Spring Boot 4.0.9, Spring AI 2.0.2 (`spring-ai-starter-mcp-server-webmvc`, streamable HTTP at `/mcp`, port 8003), Java 21, Maven. Tools are `@McpTool` methods; Spring AI turns them into the MCP tool list and their JSON Schemas.
- **Independent service, no shared code.** Own `pom.xml`, Dockerfile, tests and CI job. It is a *client* of the existing Postgres schema (Alembic in the Python API still owns it; deciding who owns the CRM schema is a Stage 6 question) and of the Python API for document search.
- **Document search stays in Python.** Embeddings and the vector store are the Python API's; the Java `search_documents` tool calls a new `POST /api/v1/documents/search`, which returns exactly what the FastMCP tool returns and writes the audit row. The Java side does not write one for that tool.
- **Same SQL, same names, same answers.** The Java SQL is the Python SQL; company-name matching is the same rule (`CompanyRef.findMentioned`); the audit rows go to the same `tool_audit_log`. Nine calls (reads, not-found cases, proposing and confirming a task) returned identical JSON from both servers when run side by side.
- **One contract, checked three ways:** a Java test (`ContractTest`) starts the real server in-process and runs the contract with a real MCP client; the CI smoke test runs `contracts/check_server.py` against the running container; the same script works by hand (`just mcp-contract`). The checker now treats "optional string" as one type however a framework spells it (Spring says `string`, Pydantic says `string or null`).
- **Optional by profile.** `docker compose --profile java up -d mcp-spring` (or `just up-java`). The API always knows its address; until it runs, the web app shows the Spring Boot radio button as "not reachable" and disabled (any server that is not both configured and reachable is disabled).
- **Parameter names are snake_case in Java** (`company_name`) on purpose: Spring AI takes a tool's argument names from the Java parameter names and the contract says `company_name`.
- **Release and dependencies:** the release workflow also publishes the `mcp-java` image; Dependabot watches Maven and the Dockerfile; CI scans the image with Trivy like the others.

## Alternatives considered

- **Java tools talking to the Python API for everything (a thin proxy):** no database code in Java, but then it teaches little and adds a hop for every CRM read.
- **Spring AI's older SSE transport or the stdio transport:** the project's transport is streamable HTTP (ADR 0015).
- **A separate repository:** decided against, in conversation with the owner, for now ([ADR 0015](0015-mcp-over-http-two-servers.md)).
- **Port the embeddings and Qdrant search to Java too:** a second implementation of retrieval would have to be kept equal to the first, for no learning value the tools do not already give.

## Consequences

- **Not verified with a real model.** No OpenRouter key was available, so no model has driven a tool call through the Java server. What was run for real: the container against the contract, nine side-by-side calls against FastMCP including the write path, the API reaching the server by its Compose name, and the search path through the API (up to the missing embeddings key, whose message now reaches the Java side).
- **Differences from the Python server:** no Host-header allowlist (Spring does not offer the SDK's DNS-rebinding check in this starter; both ports are published to the host in Compose, so treat them as local-development ports); a tool error from Java is an MCP error result, as from Python.
- **A bug the unit tests could not see:** the JDK HTTP client offers an HTTP/2 upgrade, and uvicorn then loses a POST body, so the first live search call got `422 body: Field required`. The client now speaks HTTP/1.1 only, and a test pins that.
- **The contract has four cases.** Both servers can still differ where it does not look; extend it when a tool changes.
- **The new CI job is not a required check yet.** Adding it to branch protection is the owner's call.
