import { apiGet } from "./client";
import type { McpServers } from "../types";

/** Which MCP tool servers exist, which are configured, and which answer right now. */
export function getMcpServers(): Promise<McpServers> {
  return apiGet<McpServers>("/api/v1/mcp/servers");
}
