import { describe, expect, it } from "vitest";
import type { ChatUsage } from "../../types";
import { fallbackNote } from "./fallbackNote";

const base: ChatUsage = {
  provider: "cloud",
  model: "google/gemma-4-31b-it:free",
  tokensIn: 10,
  tokensOut: 5,
  latencyMs: 900,
  estimatedCost: 0,
  fallbackUsed: false,
  fallbackFrom: null,
  fallbackFromModel: null,
};

describe("fallbackNote", () => {
  it("says nothing when the first choice answered", () => {
    expect(fallbackNote(base)).toBeNull();
  });

  it("names both models when a cloud model fell back to another cloud model", () => {
    const note = fallbackNote({
      ...base,
      fallbackUsed: true,
      fallbackFrom: "cloud",
      fallbackFromModel: "liquid/lfm-2.5-2.6b:free",
    });
    expect(note).toBe(
      "liquid/lfm-2.5-2.6b:free was unavailable (rate limit or error): answered by google/gemma-4-31b-it:free instead.",
    );
  });

  it("names the providers when the whole provider was unavailable", () => {
    const note = fallbackNote({
      ...base,
      provider: "ollama",
      model: "qwen2.5:3b",
      fallbackUsed: true,
      fallbackFrom: "cloud",
      fallbackFromModel: "liquid/lfm-2.5-2.6b:free",
    });
    expect(note).toBe("Cloud (OpenRouter) was unavailable: answered via Local (Ollama) instead.");
  });
});
