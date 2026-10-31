import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { McpServerPicker } from "./McpServerPicker";
import { unavailableReason } from "./mcpServerStatus";
import type { McpServerInfo } from "../../types";

const fastmcp: McpServerInfo = { id: "fastmcp", label: "FastMCP (Python)", configured: true, reachable: true };
const spring: McpServerInfo = { id: "springboot", label: "Spring Boot (Java)", configured: false, reachable: false };

describe("McpServerPicker", () => {
  it("selects the server's default when nothing was chosen", () => {
    render(<McpServerPicker servers={[fastmcp, spring]} defaultId="fastmcp" value="" onChange={() => {}} />);
    expect(screen.getByLabelText(/FastMCP/)).toBeChecked();
    expect(screen.getByLabelText(/Spring Boot/)).not.toBeChecked();
  });

  it("disables a server that is not configured and says why", () => {
    render(<McpServerPicker servers={[fastmcp, spring]} defaultId="fastmcp" value="" onChange={() => {}} />);
    expect(screen.getByLabelText(/Spring Boot/)).toBeDisabled();
    expect(screen.getByText("(not configured)")).toBeInTheDocument();
  });

  it("disables a server that is configured but not answering", () => {
    const down = { ...spring, configured: true, reachable: false };
    render(<McpServerPicker servers={[fastmcp, down]} defaultId="fastmcp" value="" onChange={() => {}} />);
    expect(screen.getByLabelText(/Spring Boot/)).toBeDisabled();
    expect(screen.getByText("(not reachable)")).toBeInTheDocument();
  });

  it("reports the chosen server's id", () => {
    const onChange = vi.fn();
    const running = { ...spring, configured: true, reachable: true };
    render(<McpServerPicker servers={[fastmcp, running]} defaultId="fastmcp" value="" onChange={onChange} />);
    fireEvent.click(screen.getByLabelText(/Spring Boot/));
    expect(onChange).toHaveBeenCalledWith("springboot");
  });

  it("explains each way a server can be unavailable", () => {
    expect(unavailableReason(fastmcp)).toBeNull();
    expect(unavailableReason(spring)).toBe("not configured");
    expect(unavailableReason({ ...fastmcp, reachable: false })).toBe("not reachable");
  });
});
