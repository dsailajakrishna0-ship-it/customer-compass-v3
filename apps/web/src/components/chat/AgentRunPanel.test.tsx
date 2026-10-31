import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentRunPanel } from "./AgentRunPanel";
import type { AgentRun } from "../../types";

describe("AgentRunPanel", () => {
  it("shows the API's error text when the agent could not run (for example no key)", () => {
    const run = { error: "GOOGLE_API_KEY is not set." } as AgentRun;
    render(<AgentRunPanel run={run} />);
    expect(screen.getByText("GOOGLE_API_KEY is not set.")).toBeInTheDocument();
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
  });

  it("shows the message for a simple question sent back to the direct modes", () => {
    render(<AgentRunPanel run={{ route: "direct", message: "Use the CRM copilot." }} />);
    expect(screen.getByText("Use the CRM copilot.")).toBeInTheDocument();
  });

  it("explains a run that stopped early", () => {
    render(<AgentRunPanel run={{ route: "agent", status: "company_not_found", message: "Name a company from the CRM to analyze." }} />);
    expect(screen.getByText("Name a company from the CRM to analyze.")).toBeInTheDocument();
  });
});
