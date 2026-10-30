import type { ChatUsage, LlmProvider } from "../../types";

const PROVIDER_LABEL: Record<LlmProvider, string> = {
  cloud: "Cloud (OpenRouter)",
  ollama: "Local (Ollama)",
};

/** The warning shown under an answer that came from a fallback, or null when the first choice answered.
 * A model-to-model fallback inside the cloud names the models; a provider-level one names the providers. */
export function fallbackNote(usage: ChatUsage): string | null {
  if (!usage.fallbackUsed) return null;
  if (usage.fallbackFrom === usage.provider && usage.fallbackFromModel) {
    return `${usage.fallbackFromModel} was unavailable (rate limit or error): answered by ${usage.model} instead.`;
  }
  const from = usage.fallbackFrom ? PROVIDER_LABEL[usage.fallbackFrom] : "The first choice";
  return `${from} was unavailable: answered via ${PROVIDER_LABEL[usage.provider]} instead.`;
}
