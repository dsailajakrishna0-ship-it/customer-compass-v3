import { useEffect, useState } from "react";
import { getMcpServers } from "../api/mcp";
import type { McpServers } from "../types";

/** Loads the MCP server list when the tool-calling mode is shown. `null` until it answers (or if it cannot). */
export function useMcpServers(enabled: boolean): McpServers | null {
  const [servers, setServers] = useState<McpServers | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    getMcpServers()
      .then((body) => { if (!cancelled && Array.isArray(body.servers)) setServers(body); })
      .catch(() => { /* optional: without the list, the server's default is used */ });
    return () => { cancelled = true; };
  }, [enabled]);

  return servers;
}
