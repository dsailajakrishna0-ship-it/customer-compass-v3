import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Citation } from "../../types";
import { CitationList } from "./CitationList";

const citation: Citation = {
  number: 1,
  documentId: 7,
  title: "Pricing overview",
  sourcePath: "pricing.md",
  docType: "note",
  companyName: "Acme Fabrication",
  similarity: 0.8123,
  snippet: "…",
};

describe("CitationList", () => {
  it("shows the number, title, company and rounded similarity", () => {
    render(<CitationList citations={[citation]} />);
    expect(screen.getByRole("listitem")).toHaveTextContent(
      "[1] Pricing overview · Acme Fabrication (note, similarity 0.81)",
    );
  });

  it("shows the page of a PDF and the sheet of a spreadsheet when there is one", () => {
    render(
      <CitationList
        citations={[
          { ...citation, page: 3 },
          { ...citation, number: 2, sheet: "Deals" },
        ]}
      />,
    );
    const [pdf, sheet] = screen.getAllByRole("listitem");
    expect(pdf).toHaveTextContent("(note, page 3, similarity 0.81)");
    expect(sheet).toHaveTextContent("(note, sheet Deals, similarity 0.81)");
  });

  it("omits the company when there is none", () => {
    render(<CitationList citations={[{ ...citation, companyName: null }]} />);
    expect(screen.getByRole("listitem")).not.toHaveTextContent("·");
  });
});
