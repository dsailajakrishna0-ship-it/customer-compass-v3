import { apiGet, apiPost } from "./client";
import type { AgentRun, ChatMessage, ChatMode, ChatResponse, LlmProvider, ModelCatalog } from "../types";

export function getCloudModels(): Promise<ModelCatalog> {
  return apiGet<ModelCatalog>("/api/v1/llm/models");
}

type SendChatRequest = {
  messages: ChatMessage[];
  provider: LlmProvider;
  model?: string;
};

// One backend endpoint per chat mode: plain LLM, RAG over documents, CRM facts + docs, MCP tool calling
const CHAT_ENDPOINTS: Record<Exclude<ChatMode, "agent">, string> = {
  general: "/api/v1/chat",
  rag: "/api/v1/chat/rag",
  crm: "/api/v1/chat/crm",
  tools: "/api/v1/chat/tools",
};

/** Routes to the right additive endpoint ("/", "/rag", "/crm") for the active chat mode. */
export function sendChat(mode: Exclude<ChatMode, "agent">, body: SendChatRequest): Promise<ChatResponse> {
  return apiPost<ChatResponse>(CHAT_ENDPOINTS[mode], body);
}

/** Stage 10: runs the bounded agent workflow. Never creates a task. */
export function recommendForAccount(body: { message: string; provider: LlmProvider; model?: string }): Promise<AgentRun> {
  return apiPost<AgentRun>("/api/v1/agent/recommend", body);
}

/** Stage 10: the only call that can create a task; `confirm: false` records a decline and writes nothing. */
export function confirmAgentTask(body: {
  companyName: string;
  note: string;
  confirm: boolean;
}): Promise<{ status?: string; message?: string; detail?: string }> {
  return apiPost("/api/v1/agent/confirm", body);
}
