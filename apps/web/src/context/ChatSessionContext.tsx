import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { ChatMessage, ChatMode, LlmProvider } from "../types";

const STORAGE_KEYS = {
  chatMode: "customer-compass:chatMode",
  provider: "customer-compass:provider",
  cloudModel: "customer-compass:cloudModel",
} as const;

function readStored<T extends string>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key);
    return (value as T) ?? fallback;
  } catch {
    // localStorage can throw in private-browsing/locked-down environments; fall back silently.
    return fallback;
  }
}

function writeStored(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Persisting the choice is a nice-to-have, not required for the app to function. */
  }
}

export const MODE_COPY: Record<ChatMode, { label: string; placeholder: string; switchNotice: string }> = {
  general: {
    label: "General chat",
    placeholder: "Ask a general question…",
    switchNotice: "Switched to general chat mode. I do not have access to CRM data here — starting a fresh conversation.",
  },
  rag: {
    label: "Document knowledge (RAG)",
    placeholder: "Ask about ingested CRM documents…",
    switchNotice: "Switched to document-grounded mode. Ask about ingested CRM documents and I'll cite my sources.",
  },
  crm: {
    label: "CRM copilot (facts + documents)",
    placeholder: "Ask about deals, pipeline, or customer conversations…",
    switchNotice: "Switched to CRM copilot mode. I can pull verified facts from the database and cite ingested documents, clearly separated.",
  },
  tools: {
    label: "Tool-calling copilot (MCP)",
    placeholder: "Ask me to look up deals, search documents, or propose a follow-up task…",
    switchNotice: "Switched to tool-calling mode. I can call live tools (company summary, open deals, document search, follow-up tasks) via MCP instead of relying only on context stuffed into the prompt.",
  },
  agent: {
    label: "Account follow-up agent",
    placeholder: "e.g. Analyze Acme Fabrication's account and recommend a next action",
    switchNotice: "Switched to the account follow-up agent. Ask me to analyze a company: an Analyst agent recommends, a Reviewer agent checks it, a Task Drafter agent drafts a task, and nothing is created until you confirm. A run can take 1–2 minutes on the local model.",
  },
};

type ChatSessionValue = {
  chatMode: ChatMode;
  switchChatMode: (next: ChatMode) => void;
  provider: LlmProvider;
  setProvider: (next: LlmProvider) => void;
  cloudModel: string;
  setCloudModel: (next: string) => void;
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
};

// Context: shares the chat mode, model provider (local Ollama vs cloud) and history across pages
const ChatSessionContext = createContext<ChatSessionValue | null>(null);

const INITIAL_MESSAGE: ChatMessage = {
  role: "assistant",
  content: "Hello — I’m Compass. Pick a chat mode above. General mode has no access to CRM data; the other modes use documents, CRM facts, tools or the follow-up agent.",
};

export function ChatSessionProvider({ children }: { children: ReactNode }) {
  const [chatMode, setChatMode] = useState<ChatMode>(() => readStored(STORAGE_KEYS.chatMode, "general"));
  const [provider, setProviderState] = useState<LlmProvider>(() => readStored(STORAGE_KEYS.provider, "ollama"));
  const [cloudModel, setCloudModelState] = useState<string>(() => readStored(STORAGE_KEYS.cloudModel, ""));
  const [messages, setMessages] = useState<ChatMessage[]>([INITIAL_MESSAGE]);

  function switchChatMode(nextMode: ChatMode) {
    // Each mode has a different system prompt and a fundamentally different
    // context shape (grounded-in-documents vs. general knowledge vs.
    // facts+citations). Carrying old messages across a mode switch lets a
    // later request "inherit" a previous mode's framing (e.g. "none of the
    // four sources mention X"), producing confusing answers. Starting a
    // fresh conversation on every mode switch keeps each mode's history
    // self-consistent.
    setChatMode(nextMode);
    writeStored(STORAGE_KEYS.chatMode, nextMode);
    setMessages([{ role: "assistant", content: MODE_COPY[nextMode].switchNotice }]);
  }

  function setProvider(next: LlmProvider) {
    setProviderState(next);
    writeStored(STORAGE_KEYS.provider, next);
  }

  function setCloudModel(next: string) {
    setCloudModelState(next);
    writeStored(STORAGE_KEYS.cloudModel, next);
  }

  const value = useMemo<ChatSessionValue>(
    () => ({ chatMode, switchChatMode, provider, setProvider, cloudModel, setCloudModel, messages, setMessages }),
    [chatMode, provider, cloudModel, messages],
  );

  return <ChatSessionContext.Provider value={value}>{children}</ChatSessionContext.Provider>;
}

export function useChatSession(): ChatSessionValue {
  const context = useContext(ChatSessionContext);
  if (!context) {
    throw new Error("useChatSession must be used within a ChatSessionProvider");
  }
  return context;
}

// Re-exported so hooks/components that only need the one-time initial
// assistant greeting don't have to import it from this module by convention.
export { INITIAL_MESSAGE };
