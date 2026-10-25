# API reference (`apps/api-py`)

Base URL (local dev / Docker Compose): `http://localhost:8001`

All endpoints except `/health` are prefixed `/api/v1`. The backend is
FastAPI (the Python backend); interactive Swagger docs are also available live at
`http://localhost:8001/docs` whenever the service is running.

## Conventions

- All request/response bodies are JSON.
- On success, chat endpoints return HTTP 200 even for "I don't know"-style
  answers (e.g. no relevant documents found) — that's a valid answer, not an
  error.
- On failure, endpoints raise an HTTP error with a JSON body containing
  **both** `error` and `detail` keys with the same message (see
  [Error shape](#error-shape) below) — this dual-key shape exists because
  the frontend's older contract (ported from the original Express API)
  reads `error`, while FastAPI's default `HTTPException` body is `detail`;
  a global exception handler in `app/main.py` adds both.

---

## `GET /health`

Confirms the process is up **and** can reach Postgres (the relational CRM database; not just that the
process is alive).

**Response 200**
```json
{ "status": "ok" }
```

**Response 503** (DB unreachable) — see [Error shape](#error-shape).

---

## `GET /api/v1/companies`

Lists all companies with deal/interaction counts, for the dashboard's
company list.

**Response 200**
```json
[
  {
    "id": 1,
    "name": "Acme Fabrication",
    "industry": "Manufacturing",
    "relationship_status": "active",
    "deal_count": 3,
    "interaction_count": 7
  }
]
```

## `GET /api/v1/companies/{company_id}`

Returns one company's profile plus contacts/deals/interactions, for the
dashboard's company detail view.

**Response 200**
```json
{
  "id": 1,
  "name": "Acme Fabrication",
  "industry": "Manufacturing",
  "website": "https://acme.example",
  "relationship_status": "active",
  "contacts": [{ "id": 1, "full_name": "Ravi Patel", "job_title": "Ops Manager", "email": "ravi@acme.example" }],
  "deals": [{ "id": 1, "name": "Renewal FY26", "amount": "25000.00", "status": "open", "expected_close_date": "2026-03-01" }],
  "interactions": [{ "id": 1, "interaction_type": "email", "subject": "Volume discount request", "occurred_at": "2026-01-10T14:00:00", "summary": "..." }]
}
```

**Response 404** — unknown `company_id`.

---

## `POST /api/v1/chat`

General-purpose chat — no document/CRM grounding (Stage 2 behavior). Always
tells the model it has no CRM access.

**Request body**
```json
{
  "messages": [{ "role": "user", "content": "What can you help me with?" }],
  "provider": "ollama",
  "model": null
}
```
| Field | Required | Notes |
| --- | --- | --- |
| `messages` | yes | 1–12 messages, `role` is `"user"` or `"assistant"`, `content` ≤ 4,000 chars and non-blank. |
| `provider` | no | `"ollama"` (local `qwen2.5:3b` via Ollama) or `"cloud"` (hosted model via OpenRouter). Defaults to `LLM_PROVIDER` env (default `"ollama"`). |
| `model` | no | Only used when `provider` resolves to `"cloud"` (or a fallback lands on `"cloud"`) — an OpenRouter model id from `GET /api/v1/llm/models`. Ignored for `"ollama"`. |

**Response 200**
```json
{
  "message": "I can answer general questions, but I don't have access to your CRM data yet.",
  "provider": "ollama",
  "usage": { "...": "see Usage object" },
  "guardrail": { "...": "see Guardrail object" }
}
```

---

## `POST /api/v1/chat/rag`

Retrieval-augmented chat: embeds the question (Google `gemini-embedding-001`, an embedding model that turns text into vectors), retrieves the nearest
document chunks from Qdrant (the vector database), and grounds the answer in them with required
`[n]` citations. Not company-scoped (general knowledge base).

**Request body** — same shape as `/chat` above.

**Response 200 (relevant documents found)**
```json
{
  "message": "Yes, the Fleet Visibility package includes alerting [4]...",
  "citations": [
    {
      "number": 1,
      "documentId": 7,
      "title": "Fleet Visibility rollout package overview",
      "sourcePath": "sample-data/documents/product-fleet-visibility.md",
      "docType": "product",
      "companyName": null,
      "similarity": 0.809125,
      "snippet": "Fleet Visibility is designed for logistics customers..."
    }
  ],
  "provider": "cloud",
  "usage": { "...": "see Usage object" },
  "guardrail": { "...": "see Guardrail object" }
}
```

**Response 200 (nothing relevant found)** — no LLM call is made in this case:
```json
{
  "message": "I could not find any ingested documents relevant to that question.",
  "citations": [],
  "provider": "cloud",
  "guardrail": { "...": "see Guardrail object" }
}
```

---

## `POST /api/v1/chat/crm`

CRM copilot: a keyword-based classifier (`app/chat/router.py`) decides
whether the question wants structured CRM facts, document retrieval, or
both, and scopes retrieval to the named company (if any) so citations never
leak across companies. Additive — never replaces `/chat` or `/chat/rag`.

**Request body** — same shape as `/chat` above.

**Response 200**
```json
{
  "message": "Acme Fabrication has 2 open deals... [1]",
  "facts": {
    "id": 1,
    "name": "Acme Fabrication",
    "industry": "Manufacturing",
    "relationshipStatus": "active",
    "openDeals": [{ "id": 1, "name": "Renewal FY26", "amount": "25000.00", "status": "open", "expectedCloseDate": "2026-03-01" }],
    "wonDealsCount": 3,
    "lostDealsCount": 1
  },
  "citations": [ "..." ],
  "scopedCompany": "Acme Fabrication",
  "provider": "ollama",
  "usage": { "...": "see Usage object" },
  "guardrail": { "...": "see Guardrail object" }
}
```

`facts` is `null` and/or `citations` is `[]` when the question didn't need
that part of the context. If neither facts nor documents matched anything,
`message` is a canned "I could not find..." response with no LLM call.

---

## `POST /api/v1/chat/tools`

Stage 9 tool-calling copilot: the model can call MCP tools
(MCP is a protocol that exposes tools to the model: `get_company_summary`, `get_open_deals`, `search_documents`,
`create_followup_task`) mid-conversation via a hand-rolled fenced
` ```tool_call ``` ` text protocol, instead of context being stuffed into
the prompt upfront like `/chat/rag`/`/chat/crm`. Additive — never replaces
the other three chat routes.

**Request body** — same shape as `/chat` above.

**Response 200**
```json
{
  "message": "Acme Fabrication has one open deal: Premium Operations Plan renewal ($48,000.00, expected close 2026-10-15).",
  "toolsUsed": [
    { "tool": "get_open_deals", "arguments": { "company_name": "Acme Fabrication" } }
  ],
  "provider": "ollama",
  "usage": { "...": "see Usage object" },
  "guardrail": { "...": "see Guardrail object" }
}
```

`toolsUsed` is `[]` if the model answered without calling any tool. For
`create_followup_task`, `arguments.confirm` reflects whether the *system*
(not the model) determined the user's latest message was an explicit
confirmation — `false` means the task was only proposed (see
`GET /api/v1/tool-audit-log` below), `true` means it was actually written
to `tasks`. See
[part-4-autonomy-protocols/09-tool-calling-mcp.md](part-4-autonomy-protocols/09-tool-calling-mcp.md)
for the full design and manual test steps.

## `POST /api/v1/agent/recommend`

Stage 10: runs the Account Follow-up Recommender (Analyst, Reviewer and Task
Drafter agents; plain-code orchestration). **Never writes.** Takes 1–2 minutes
with the local model.

**Request:** `{ "message": "Analyze Acme Fabrication account and recommend a next action", "provider": "ollama", "model": null }` (`provider` and `model` optional).

**Response 200** — simple questions return `{ "route": "direct", "message": "..." }`. Otherwise:
```json
{
  "route": "agent",
  "status": "completed",
  "company": { "id": 1, "name": "Acme Fabrication" },
  "trace": [{ "index": 1, "kind": "tool", "name": "get_company_summary", "input_summary": "...", "output_summary": "...", "status": "ok", "duration_ms": 12 }],
  "evidence": [{ "label": "E1", "source": "...", "text": "..." }],
  "recommendation": { "action": "...", "rationale": "...", "evidence": ["E3", "E6"] },
  "review": { "approved": true, "verdict": "approve", "reasons": [], "revisions": 0 },
  "proposedTask": { "companyName": "Acme Fabrication", "note": "..." },
  "guardrail": { "flagged": false, "reasons": [] },
  "llmCalls": 3
}
```
`status` is one of `completed`, `company_not_found`, `budget_exceeded`, `timed_out` (the last three return a `message` and a partial `trace`). Limits: `AGENT_MAX_STEPS` (8), `AGENT_TIMEOUT_SECONDS` (180), `AGENT_MAX_REVISIONS` (1).

## `POST /api/v1/agent/confirm`

Stage 10: the only agent write path. **Request:** `{ "companyName": "Acme Fabrication", "note": "...", "confirm": true }`. `confirm: false` records a decline and creates nothing. `confirm: true` creates the task through the Stage 9 tool (audited in `tool_audit_log`); `404` if the company is not found. See [part-4-autonomy-protocols/10-agentic-assistant.md](part-4-autonomy-protocols/10-agentic-assistant.md).

### `GET /api/v1/security-audit-log` (Stage 8.c)

Returns recorded guardrail detections, newest first. Query params: `limit`
(1–500, default 50), `event_type` (`input`, `document`, `tool`, `output`),
`pattern` (e.g. `override_instructions`).

```json
[{ "id": 7, "event_type": "input", "endpoint": "chat/rag", "pattern": "override_instructions",
   "location": "user_input", "excerpt": "Ignore all previous instructions",
   "created_at": "2026-10-22 09:41:03+00" }]
```

---

## `GET /api/v1/llm/models`

Lists OpenRouter's current free-tier models (used to populate the web UI's
"OpenRouter model" dropdown) plus a couple of disabled example paid models,
shown for reference only. Cached server-side for 5 minutes.

**Response 200**
```json
{
  "free": [{ "id": "liquid/lfm-2.5-2.6b:free", "name": "LiquidAI: LFM2.5-2.6B (free)" }],
  "paid": [{ "id": "openai/gpt-4o-mini", "name": "OpenAI: GPT-4o-mini" }]
}
```

**Response 503** — couldn't reach OpenRouter.

---

## `POST /api/v1/documents/ingest`

Runs the full parse → chunk → embed → store pipeline over
`sample-data/documents` into Qdrant (plus a `documents`/`ingestion_runs` row
in Postgres).

**Response 200**
```json
{ "ingestionRunId": 3, "documentsProcessed": 7, "chunksCreated": 42, "status": "completed" }
```

**Response 502** (partial/failed run — `status` is `"failed"`, body includes `error`)
**Response 500** (the ingestion call itself raised)

## `GET /api/v1/documents`

Lists ingested documents with their chunk counts (debugging retrieval).

```json
[{ "id": 7, "title": "Fleet Visibility rollout package overview", "docType": "product", "sourcePath": "sample-data/documents/product-fleet-visibility.md", "companyName": null, "chunkCount": 6 }]
```

## `GET /api/v1/documents/ingestion-runs`

Most recent 10 ingestion runs, most recent first.

```json
[{ "id": 3, "startedAt": "2026-10-10T09:00:00", "completedAt": "2026-10-10T09:00:12", "status": "completed", "embeddingModel": "gemini-embedding-001", "documentsProcessed": 7, "chunksCreated": 42, "error": null }]
```

---

## `GET /api/v1/tasks`

Stage 9: lists follow-up tasks created by `create_followup_task` (only
appears here once confirmed — a merely-proposed task is tracked only in
`tool_audit_log`, below — the table that records every MCP tool call). Optional `?company_id=` filter.

```json
[{ "id": 3, "company_id": 2, "company_name": "Northstar Logistics", "note": "Send Q4 pricing sheet", "status": "open", "created_at": "2026-10-18 17:59:44.804461+00" }]
```

## `GET /api/v1/tool-audit-log`

Stage 9: every MCP tool invocation (read and mutating), most recent first.
Optional `?limit=` (default 50).

```json
[{
  "id": 10,
  "tool_name": "create_followup_task",
  "arguments": { "company_name": "Northstar Logistics", "note": "Send Q4 pricing sheet", "confirm": true },
  "status": "confirmed",
  "result_summary": "Created task #3 for Northstar Logistics",
  "company_id": 2,
  "created_at": "2026-10-18 17:59:44.811977+00"
}]
```

`status` is one of `executed` (read tools), `proposed`/`confirmed`
(`create_followup_task`'s two-step flow), or `error` (e.g. company not
found).

---

## Usage object (Stage 7)

Every successful `/chat*` response includes a `usage` object — Stage 7's
production telemetry: which provider/model actually answered (may differ
from the request if automatic fallback kicked in), token counts, latency,
and a rough cost estimate.

```json
{
  "provider": "ollama",
  "model": "qwen2.5:3b",
  "tokensIn": 521,
  "tokensOut": 37,
  "latencyMs": 23841,
  "estimatedCost": 0.0,
  "fallbackUsed": true,
  "fallbackFrom": "cloud"
}
```

| Field | Notes |
| --- | --- |
| `provider` / `model` | The provider/model that actually generated the answer. |
| `tokensIn` / `tokensOut` | From the provider's own response (`prompt_eval_count`/`eval_count` for Ollama, `usage.prompt_tokens`/`usage.completion_tokens` for OpenRouter). Can be `null` if the provider didn't report them. |
| `latencyMs` | Wall-clock time for the provider HTTP call only (not including retrieval/DB time). |
| `estimatedCost` | `0.0` for all current models (every OpenRouter model offered in the UI is free-tier; Ollama is always local/free). A real per-token price can be added per-model in `cloud.py`'s `OPENROUTER_PRICE_PER_1K_TOKENS` map without touching call sites. |
| `fallbackUsed` / `fallbackFrom` | `true`/the original provider's name if the requested provider failed and this answer came from the automatic retry with the other provider instead. |

---

## Guardrail object (Stage 8)

Every successful `/chat*` response also includes a `guardrail` object —
Stage 8's prompt-injection telemetry: whether the rule-based prompt guard (a text scan for injection phrases) found
and neutralized anything in the user's message and/or a retrieved document
before it reached the LLM.

```json
{
  "flagged": true,
  "reasons": [
    "override_instructions (user_input)",
    "reveal_system_prompt (document: Fleet Visibility rollout package overview)"
  ]
}
```

| Field | Notes |
| --- | --- |
| `flagged` | `true` if any scanned text (the user's message, and for `/chat/rag`/`/chat/crm` each retrieved document chunk) matched a known injection pattern. |
| `reasons` | One entry per match: `"<pattern_name> (<location>)"`. `location` is `"user_input"`, `"document: <document title>"`, `"tool: ..."` or `"output"` (Stage 8.b: the model's answer was redacted for `system_prompt_leak`, `jailbreak_compliance` or `cross_customer_leak`). Pattern `llm_classifier` appears when `GUARD_MODE` is `llm`/`both` (8.d). Empty list when `flagged` is `false`. |

Flagged text is **neutralized, not blocked** — the matched phrase is
redacted before reaching the LLM, but the request still proceeds and still
returns an answer. Citations in the response still show the **original,
un-redacted** document content, so you can see exactly what was retrieved.
See [part-3-trust-safety/08-prompt-injection-guardrails.md](part-3-trust-safety/08-prompt-injection-guardrails.md)
for the full design and manual test steps.

---

## Error shape

Any non-2xx response has this body shape (both keys always present, same
message):

```json
{
  "error": "The cloud model (not-a-real-model) is currently unavailable: ...",
  "detail": "The cloud model (not-a-real-model) is currently unavailable: ..."
}
```

| Status | Meaning |
| --- | --- |
| 404 | Unknown resource (e.g. company id). |
| 500 | Ingestion pipeline raised unexpectedly. |
| 502 | Ingestion ran but did not complete successfully. |
| 503 | Could not reach/complete an upstream call (DB, Qdrant, LLM provider, OpenRouter model list) — see the `error`/`detail` message for specifics; chat routes only return this if **both** the requested provider and its automatic fallback (Stage 7) failed. |
