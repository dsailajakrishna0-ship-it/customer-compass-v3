# MCP tool contract

`mcp-tools.json` is the one description of what **every** MCP tool server for Customer Compass must do. It belongs to neither implementation:

| Server | Where | Compose service | Config id |
| --- | --- | --- | --- |
| FastMCP (Python) | `apps/api-py/app/mcp/` | `mcp-fastmcp` (port 8002) | `fastmcp` |
| Spring Boot (Java) | `services/mcp-java/` | `mcp-spring` (port 8003, profile `java`) | `springboot` |

It lists the tools with their argument names, types and required fields, and a few calls with the answers expected on the demo data (migration 0002). Calls never write data.

```bash
just up        # or: docker compose up -d db qdrant api-py
just mcp-contract http://localhost:8002/mcp
```

CI runs the same check against both containers (`Compose smoke test`). Without any services running, `tests/test_mcp_contract.py` keeps the FastMCP server's tool definitions equal to this file, and the Java `ContractTest` starts the Spring Boot server in-process and runs the whole contract with a real MCP client. `search_documents` is checked for its schema only, because a real call needs the embeddings API and a populated vector store.

To change a tool: change this file, the Pydantic model in `apps/api-py/app/mcp/schemas.py`, and every server, in one pull request.
