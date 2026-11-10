import type { McpServerInfo } from "../../types";

/** Why a server cannot be chosen right now, or null when it can. */
export function unavailableReason(server: McpServerInfo): string | null {
  if (!server.configured) return "not configured";
  if (!server.reachable) return "not reachable";
  return null;
}

/**
 * The choice to keep: the saved one if that server can be used right now, otherwise "" (meaning
 * "use the server's default"). A choice saved while the Java server was running must not stay
 * selected after it stops.
 */
export function usableChoice(choice: string, servers: McpServerInfo[]): string {
  if (!choice) return "";
  const server = servers.find((candidate) => candidate.id === choice);
  return server && unavailableReason(server) === null ? choice : "";
}
