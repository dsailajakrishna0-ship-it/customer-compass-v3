import type { McpServerInfo } from "../../types";
import { unavailableReason } from "./mcpServerStatus";

type McpServerPickerProps = {
  servers: McpServerInfo[];
  /** the server's default (MCP_BACKEND) */
  defaultId: string;
  /** the user's choice; empty means "use the default" */
  value: string;
  onChange: (id: string) => void;
};

/** Radio buttons: which MCP tool server answers tool-calling questions (FastMCP in Python or Spring Boot in Java). */
export function McpServerPicker({ servers, defaultId, value, onChange }: McpServerPickerProps) {
  const selected = value || defaultId;
  return (
    <fieldset className="mcp-picker">
      <legend>Tool server:</legend>
      {servers.map((server) => {
        const reason = unavailableReason(server);
        return (
          <label key={server.id} className={reason ? "mcp-option unavailable" : "mcp-option"}>
            <input
              type="radio"
              name="mcp-server"
              value={server.id}
              checked={selected === server.id}
              disabled={!server.configured}
              onChange={() => onChange(server.id)}
            />
            {server.label}
            {reason && <small> ({reason})</small>}
          </label>
        );
      })}
    </fieldset>
  );
}
