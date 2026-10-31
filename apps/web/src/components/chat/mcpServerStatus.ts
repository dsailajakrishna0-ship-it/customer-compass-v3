import type { McpServerInfo } from "../../types";

/** Why a server cannot be chosen right now, or null when it can. */
export function unavailableReason(server: McpServerInfo): string | null {
  if (!server.configured) return "not configured";
  if (!server.reachable) return "not reachable";
  return null;
}
