import { describe, expect, it } from "vitest";
import type { ChatUsage } from "../../types";
import { fallbackNote } from "./fallbackNote";

const base: ChatUsage = {
  model: "google/gemma-4-31b-it:free",
  tokensIn: 10,
  tokensOut: 5,
  latencyMs: 900,
  estimatedCost: 0,
  fallbackUsed: false,
  fallbackFromModel: null,
};

describe("fallbackNote", () => {
  it("says nothing when the first choice answered", () => {
    expect(fallbackNote(base)).toBeNull();
  });

  it("names both models when a fallback model answered", () => {
    const note = fallbackNote({ ...base, fallbackUsed: true, fallbackFromModel: "liquid/lfm-2.5-2.6b:free" });
    expect(note).toBe(
      "liquid/lfm-2.5-2.6b:free was unavailable (rate limit or error): answered by google/gemma-4-31b-it:free instead.",
    );
  });

  it("still gives a sensible note if the failed model is unknown", () => {
    expect(fallbackNote({ ...base, fallbackUsed: true })).toBe(
      "The first-choice model was unavailable (rate limit or error): answered by google/gemma-4-31b-it:free instead.",
    );
  });
});
