# Chat Request Flow (current implementation)

This document replaces the old Stage-2-only version
(`docs/part-1-foundations/02-request-flow.md`), which described a single
`POST /api/chat` call straight out of a monolithic `main.tsx`. Since the
[frontend refactor](./fe-architecture-overview.md) and later backend stages,
the flow goes through dedicated hooks/context/api layers on the frontend and
four chat endpoints on the FastAPI backend (the Python API server) (`/api/v1/chat`, `/rag`, `/crm`,
`/tools`). It now lives in `docs/fe/` because most
of what changed is how the **frontend** builds and sends the request, not the
model-calling logic itself.

## Where each responsibility lives today

| Responsibility | File |
| --- | --- |
| Chat input + submit handling | `apps/web/src/components/chat/ChatInput.tsx` |
| Chat history, mode/provider/model state | `apps/web/src/context/ChatSessionContext.tsx` |
| Building the request + calling the API | `apps/web/src/hooks/useChat.ts` |
| Picking the right endpoint for the mode | `apps/web/src/api/chat.ts` |
| Shared `fetch` wrapper (base URL `http://localhost:8001`) | `apps/web/src/api/client.ts` |
| Mounting the routers under `/api/v1` | `apps/api-py/app/main.py` |
| General / RAG / CRM / tools route handlers | `apps/api-py/app/routes/chat.py` |
| Picking local (Ollama — runs the local generating model) vs. cloud (OpenRouter — hosted generating models) + fallback (one automatic retry on the other provider, Stage 7) | `apps/api-py/app/llm/provider.py` |
| Document retrieval for grounding | `apps/api-py/app/rag/retrieve.py` |
| Structured CRM facts + mode classification (the query router that decides DB facts vs. documents) | `apps/api-py/app/crm/queries.py`, `apps/api-py/app/chat/router.py` |
| Prompt-injection scan (Stage 8; the prompt guard, a rule-based text scan) | `apps/api-py/app/guardrails/prompt_guard.py` |
| MCP tool server/client (Stage 9; MCP is a protocol that exposes tools to the model) | `apps/api-py/app/mcp/` |

## Pictorial flow — frontend side

```text
┌───────────────┐   submit    ┌──────────────────┐
│  ChatInput.tsx │ ──────────▶ │  useChat() hook   │
└───────────────┘             └─────────┬─────────┘
                                         │ reads chatMode / provider / cloudModel
                                         ▼
                              ┌────────────────────────┐
                              │ ChatSessionContext      │
                              │  (chatMode, provider,   │
                              │   cloudModel, messages)  │
                              └─────────┬──────────────┘
                                         │ sendChat(chatMode, body)
                                         ▼
                              ┌────────────────────────┐
                              │  api/chat.ts             │
                              │  picks endpoint by mode: │
                              │   general → /api/v1/chat │
                              │   rag     → /api/v1/chat/rag │
                              │   crm     → /api/v1/chat/crm │
                              │   tools   → /api/v1/chat/tools │
                              └─────────┬──────────────┘
                                         │ apiPost()
                                         ▼
                              ┌────────────────────────┐
                              │  api/client.ts           │
                              │  (fetch + JSON wrapper)  │
                              └─────────┬──────────────┘
                                         ▼
                                 FastAPI service (see below)
                                         │
                                         ▼
                         useChat() appends the ChatMessage
                         (content, provider, citations, facts,
                          usage, guardrail, toolsUsed)
                         to ChatSessionContext → MessageList
                         → MessageBubble re-renders
```

## Pictorial flow — backend side (per chat mode)

```text
POST /api/v1/chat   POST /api/v1/chat/rag     POST /api/v1/chat/crm      POST /api/v1/chat/tools
     │                    │                         │                          │
     ▼                    ▼                         ▼                          ▼
ChatRequest model   ChatRequest model        ChatRequest model          ChatRequest model
(pydantic: 1–12 msgs, ≤4,000 chars each)
     │                    │                         │                          │
scan_and_neutralize  scan_and_neutralize      scan_and_neutralize        scan_and_neutralize
(user message)       (user msg + chunks)      (user msg + chunks)        (user msg + tool results)
     │                    │                         │                          │
     │             retrieve_relevant_chunks()  classify the question          loop (max 4 iterations):
     │                    │                     ├─ structured? → CRM facts      model emits ```tool_call```
     │             build_context(chunks)        └─ documents?  → retrieval      → MCP client → MCP server
     │                    │                    builds combined prompt           (stdio subprocess)
     ▼                    ▼                         ▼                          ▼
          generate(system_prompt, messages, provider, model)
                    │
         ┌──────────┴───────────┐
         ▼                      ▼
   Ollama (local)        OpenRouter (cloud)
   qwen2.5:3b            user-picked free model
         │                      │
         └──────────┬───────────┘
                     ▼
     { message, provider, usage, guardrail,
       citations?, facts?, scopedCompany?, toolsUsed? }
```

## 1. User submits a question

`ChatInput` (`components/chat/ChatInput.tsx`) is a thin, controlled input —
it only owns the text box value and calls `onSubmit` on form submit. All
logic lives in `useChat()`:

```ts
// apps/web/src/hooks/useChat.ts
function askQuestion(event: FormEvent<HTMLFormElement>) {
  event.preventDefault();
  const text = question.trim();
  if (!text || isAsking) return;

  const history = [...messages, { role: "user" as const, content: text }];
  setMessages(history);
  setQuestion("");
  setIsAsking(true);

  const requestBody: { messages: ChatMessage[]; provider: LlmProvider; model?: string } = {
    messages: history.slice(-12),
    provider,
  };
  if (provider === "cloud" && cloudModel) requestBody.model = cloudModel;

  sendChat(chatMode, requestBody)
    .then((body) => setMessages((current) => [...current, {
      role: "assistant",
      content: body.message ?? body.error ?? "Something went wrong.",
      citations: body.citations,
      facts: body.facts,
      scopedCompany: body.scopedCompany,
      provider: body.provider,
      usage: body.usage,
      guardrail: body.guardrail,
      toolsUsed: body.toolsUsed,
    }]))
    .catch(() => setMessages((current) => [...current, {
      role: "assistant",
      content: "I could not reach the API. Check that the local services are running.",
    }]))
    .finally(() => setIsAsking(false));
}
```

`chatMode`, `provider`, and `cloudModel` come from `useChatSession()`
(`context/ChatSessionContext.tsx`) — the same values the user picked in
`ChatModeSelector` and that are persisted to `localStorage`.

## 2. The frontend picks an endpoint by chat mode

```ts
// apps/web/src/api/chat.ts
const CHAT_ENDPOINTS: Record<ChatMode, string> = {
  general: "/api/v1/chat",
  rag: "/api/v1/chat/rag",
  crm: "/api/v1/chat/crm",
  tools: "/api/v1/chat/tools",
};

export function sendChat(mode: ChatMode, body: SendChatRequest) {
  return apiPost<ChatResponse>(CHAT_ENDPOINTS[mode], body);
}
```

There are four modes, each hitting a different FastAPI route:

| Mode | Endpoint | Behavior |
| --- | --- | --- |
| `general` | `POST /api/v1/chat` | Plain LLM chat, no CRM/document grounding (original Stage 2 behavior) |
| `rag` | `POST /api/v1/chat/rag` | Retrieves cited document chunks and grounds the answer in them |
| `crm` | `POST /api/v1/chat/crm` | Classifies the question, pulls structured CRM facts and/or cited documents, and combines both in the prompt |
| `tools` | `POST /api/v1/chat/tools` | Stage 9: the model can call MCP tools (CRM summary, open deals, document search, propose a follow-up task) mid-conversation |

## 3. FastAPI validates and routes the request

Every route shares the same pydantic request model before calling any model
(`ChatRequest` in `apps/api-py/app/routes/chat.py`): 1–12 messages, each with
a `user`/`assistant` role and non-blank content of at most 4,000 characters.
Invalid requests are rejected with a 4xx error before any LLM call. Each
route then runs the Stage 8 prompt-injection scan on the user message (and on
any retrieved/tool-returned content) before building the prompt.

- **`/api/v1/chat`** calls `generate(GENERAL_SYSTEM_PROMPT, messages, provider, model)` directly.
- **`/api/v1/chat/rag`** calls `retrieve_relevant_chunks(question)`, builds a numbered source context with `build_context()`, and asks the model to cite `[1]`, `[2]`, etc. If nothing clears the similarity threshold it returns a canned "nothing relevant" answer without calling the LLM.
- **`/api/v1/chat/crm`** classifies the question first (`app/chat/router.py`) to decide whether it needs structured facts (`app/crm/queries.py`), document retrieval, or both, then combines a "Verified CRM facts" block (never needs a citation) with a "Source documents" block (always needs one).
- **`/api/v1/chat/tools`** runs a bounded loop (max 4 iterations) in which the model may emit a fenced `tool_call` block that is executed through the MCP client; mutating tools only run after the user confirms in their next message.

## 4. `generate()` picks the LLM provider

```python
# apps/api-py/app/llm/provider.py (conceptually)
generate(system_prompt, messages, provider, model)
  # provider == "ollama" -> Ollama (qwen2.5:3b)
  # provider == "cloud"  -> OpenRouter with the user-picked free model
  # on failure: retry once with the other provider, flag usage.fallbackUsed
```

`provider` and `model` are optional per-request overrides sent from the UI's
provider/model selectors; if omitted, the API falls back to the
`LLM_PROVIDER` environment variable (default `ollama`).

## 5. The response flows back up

The API always responds with the same core shape, with optional fields depending
on mode:

```json
{
  "message": "…",
  "provider": "ollama",
  "usage": { "…": "tokens, latency, cost, fallback flag (Stage 7)" },
  "guardrail": { "flagged": false, "reasons": [] },
  "citations": [{ "number": 1, "title": "…", "similarity": 0.83 }],
  "facts": { "name": "Acme Fabrication", "openDeals": [] },
  "scopedCompany": "Acme Fabrication",
  "toolsUsed": []
}
```

(`citations`/`facts`/`scopedCompany` appear in RAG/CRM modes, `toolsUsed` in
tools mode. See [api-reference.md](../api-reference.md) for the exact shapes.)

`useChat()` appends this as a new `ChatMessage` to `ChatSessionContext`,
which re-renders `MessageList` → `MessageBubble`, conditionally showing
`CrmFactsPanel` (for `facts`) and `CitationList` (for `citations`).

## Why this moved out of `docs/part-1-foundations/`

The original `02-request-flow.md` was accurate for Stage 2 only — it quoted
`useState` and `askQuestion` living directly inside `main.tsx`, which no
longer exists after the [frontend layering refactor](./fe-architecture-overview.md).
Keeping a stage-numbered doc that described stale frontend code was more
confusing than useful, so this rewritten version lives alongside the other
frontend docs in `docs/fe/` instead.
