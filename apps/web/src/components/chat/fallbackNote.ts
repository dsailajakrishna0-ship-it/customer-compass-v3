import type { ChatUsage } from "../../types";

/** The warning shown under an answer that came from a fallback model, or null when the first choice answered. */
export function fallbackNote(usage: ChatUsage): string | null {
  if (!usage.fallbackUsed) return null;
  const from = usage.fallbackFromModel ?? "The first-choice model";
  return `${from} was unavailable (rate limit or error): answered by ${usage.model} instead.`;
}
