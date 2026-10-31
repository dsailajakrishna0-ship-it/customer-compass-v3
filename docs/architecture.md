# Architecture overview

> **Status:** describes the seed state (V2 @ `v2-final`). Each V3 stage updates this file in the same PR that changes the architecture (see [roadmap.md](roadmap.md)). Technology choices live in [tech-stack.md](tech-stack.md).

This is the "how all the pieces fit together" map for Customer Compass.
For the per-stage build history, see [tech-stack.md](tech-stack.md) and the
`part-*/` stage documents. For the frontend's internal layering, see
[fe/fe-architecture-overview.md](fe/fe-architecture-overview.md).

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](ai-terms.md)

## System diagram

> In short: **React + Vite** is the browser UI, **FastAPI** is the backend, **Postgres** holds the CRM tables (schema built by Alembic migrations), **🟩Qdrant** is the 🟪vector DB, **🟩OpenRouter** gives access to hosted free generating models (through the 🟦LiteLLM gateway), and Google **`gemini-embedding-001`** is the 🟪embedding model (text → vectors, not a chat model).

```
┌─────────────────────────────┐
│   apps/web (React + Vite)   │   http://localhost:5173
│   dashboard + chat UI       │
└──────────────┬──────────────┘
               │ fetch() — JSON over HTTP
               ▼
┌─────────────────────────────────────────────────────────────┐
│           apps/api-py (FastAPI, Python, uv)                 │   http://localhost:8001
│                                                               │
│  /health             — DB connectivity check                 │
│  /api/v1/companies*  — company list/detail (Postgres)        │
│  /api/v1/documents*  — ingest pipeline + inspection           │
│  /api/v1/chat*       — general / RAG / CRM / tools chat       │
│  /api/v1/llm/models  — OpenRouter free/paid model catalog     │
│  /api/v1/tasks, /api/v1/tool-audit-log — Stage 9 tool output  │
│  /api/v1/agent/recommend, /confirm — Stage 10 agent workflow  │
│                                                               │
│  app/db.py        — Postgres connection pool (asyncpg)        │
│  app/rag/         — chunking, embeddings, Qdrant client        │
│  app/chat/router.py — keyword-based RAG-vs-CRM query router   │
│  app/crm/queries.py — structured CRM fact lookups              │
│  app/llm/         — gateway.py (LiteLLM: chain, retries,       │
│                      fallback), types.py (GenerationResult)    │
│  app/guardrails/  — prompt_guard.py, audit.py, llm_guard.py (Stage 8)  │
│  app/mcp/         — server.py/tools.py/client.py (Stage 9)    │
│  app/agent/       — workflow, agents, trace, policies (Stage 10)│
└───────┬───────────────────┬───────────────────┬───────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌─────────────────────┐
│   Postgres      │   │    Qdrant      │   │  OpenRouter (cloud) │
│ (postgres:17,   │   │ (vector store  │   │  hosted free models,│
│  relational data│   │  for document  │   │  called through     │
│  only in v2:    │   │  chunk         │   │  LiteLLM (an OpenAI-│
│  companies,     │   │  embeddings;   │   │  style API), with an│
│  deals, contacts,│  │  vectors come  │   │  ordered fallback   │
│  interactions,  │   │  from Google   │   │  chain of models    │
│  ingestion_runs,│   │  gemini-       │   │  (sub-stage 1.2)    │
│  tasks,         │   │  embedding-001)│   │                     │
│  tool_audit_log)│   │                │   │                     │
└───────────────┘   └───────────────┘   └─────────────────────┘
```

## Stage-by-stage: what's new at each layer

A per-stage comparison, from Stage 1 through Stage 10. **Bold** = introduced at that stage; everything else in a row
is reused unchanged from an earlier stage. Read top to bottom to see the
architecture diagram above build up incrementally. Full prose write-up per
stage: [tech-stack.md](tech-stack.md).

| Stage | New component(s) | New capability unlocked | Builds on |
| --- | --- | --- | --- |
| **1 — CRM Foundation** | **PostgreSQL** (companies, contacts, deals, interactions) | Structured CRM data exists at all; no 🟪LLM/AI yet | — |
| **2 — First 🟪LLM Chat** | A small local model (`qwen2.5:3b`; removed in V3 sub-stage 1.3), `/api/v1/chat` | First chat/completion endpoint; no CRM data access yet | Stage 1 DB (unused by chat so far) |
| **3 — Basic 🟪RAG** | **🟪Embeddings** + 🟪vector search, `/api/v1/chat/rag` (originally a local `mxbai-embed-large` embedding model + **`pgvector`** in the same Postgres DB; in v2 now **Google `gemini-embedding-001`** + **🟩Qdrant**) | Answers grounded in 🟪retrieved, cited document 🟪chunks instead of the model's own knowledge | Stage 1 DB, Stage 2 chat model |
| **4 — Cloud 🟪LLM Provider** | **🟩OpenRouter** (cloud, free tier), `GET /api/v1/llm/models`, Model dropdown in UI | Live, per-request choice of hosted model (V2 also offered a local/cloud switch; V3 is cloud-only) | Stage 2 chat plumbing |
| **5 — Realistic CRM 🟪RAG** | **Query router** (`chat/router.py`, a keyword classifier that picks DB facts vs. documents), **`crm/queries.py`**, `/api/v1/chat/crm`, 3-way chat-mode selector | Questions routed to structured SQL facts, document retrieval, or both — and the UI visibly separates "verified facts" from "cited claims" | Stage 1 DB, Stage 3 retrieval |
| **6 — 🟪Retrieval Evaluation** | **🟦promptfoo** 🟪eval suite (`evals/`; a harness that sends test questions to the live API and grades the answers), 🟪LLM-as-judge rubric (a second model, `qwen2.5:7b`, grades the answers) | Retrieval/grounding correctness and refusal behavior are now measurable, not just manually eyeballed — used to empirically tune `MIN_SIMILARITY` | Stage 3 retrieval, Stage 5 CRM routing |
| **7 — Production Concerns** | **Cross-provider auto-fallback** (retry once on the other provider), **per-request `usage` telemetry** | A failing provider no longer surfaces a hard error — it silently retries on the other provider and *tells you it did* (fallback flag + cost/latency footer in UI) | Stage 4 dual providers |
| **8 — 🟪Prompt-Injection 🟪Guardrails** | **Rule-based input/document guard** (the 🟪prompt guard, a text scan for injection phrases), `<untrusted_context>` delimiting, `guardrail` field on every response | Injection attempts (direct or planted in a document) are neutralized in place and surfaced visibly, instead of silently succeeding or blocking the whole request | Stage 3 document ingestion, Stage 5 CRM chat, Stage 7 visibility pattern |
| **9 — 🟪Tool Calling (🟦MCP)** | **🟦MCP server/client** (`app/mcp/`; MCP is a protocol that exposes tools to the model), native tool calling (since 2.1; Pydantic schemas in `app/mcp/schemas.py`), `/api/v1/chat/tools`, **`tasks`**/**`tool_audit_log`** (records every tool call) tables | Model can call live tools **mid-conversation** (read CRM/docs, propose+confirm a mutating action) instead of everything being stuffed into the prompt upfront | Stage 1 DB, Stage 3 retrieval, Stage 5 CRM queries, Stage 8 guardrail (applied to tool results too) |
| **10 — 🟪Agentic Assistant** | **`app/agent/`** (3 agents: Analyst, Reviewer, Task Drafter; orchestration is plain code), `POST /api/v1/agent/recommend` and `/agent/confirm`, an inspectable trace, the "Account follow-up agent" chat mode — see [part-4-autonomy-protocols/10-agentic-assistant.md](v2-baseline/part-4-autonomy-protocols/10-agentic-assistant.md) | A bounded multi-step review (max 8 steps, 180 s) that ends in a confirmation gate; only `/agent/confirm` can create a task. Which pattern to use when: [agent-boundaries.md](agent-boundaries.md) | Stage 9 tools, Stage 8 guardrails, Stage 5 CRM queries |

## Why two databases

Postgres and 🟩Qdrant have different jobs and neither replaces the other here:

- **Postgres** (plain `postgres:17` image; schema and demo data come from
  Alembic migrations, see [ADR 0005](adr/0005-database-migrations.md)) holds all relational/structured
  CRM data: companies, contacts, deals, interactions, and ingestion run
  history, plus the Stage 9 `tasks` and `tool_audit_log` tables. This is
  what `/api/v1/companies*`, `/api/v1/tasks`, `/api/v1/tool-audit-log` and
  the CRM-facts half of `/api/v1/chat/crm` read from.
- **🟩Qdrant** holds document 🟪chunk 🟪embeddings for 🟪retrieval. v1 used
  🟩pgvector's vector column directly in Postgres; v2 migrated to a dedicated
  🟪vector database (Stage migration documented in `docs/tech-stack.md`) to
  learn a real vector-DB's API (collections, payload filtering by
  `company_id` for CRM-mode scoping, 🟪similarity search) rather than treating
  vector search as "just another SQL column."

## Why chat models are cloud-only (V3)

V2 offered two ways to generate answers: a small local model (private and free, but limited by local hardware,
which showed in terse answers and odd citation placement) and hosted models through 🟩OpenRouter. V3 removed
the local one (sub-stage 1.3, [ADR 0010](adr/0010-cloud-only-models.md)):

- **🟩OpenRouter free models** can be much larger than anything a laptop runs, and they are swappable. The price
  is internet access, rate limits and the usual cloud instability, which the 🟪model gateway absorbs
  (`app/llm/gateway.py`, sub-stage 1.2): a failing model hands over to the next one in an ordered chain
  (`models.yaml`), with retries for timeouts and server errors (full design:
  [Stage 1 guide](stages/01-model-layer.md#concept-4--calling-models-safely-the-model-gateway)).
- **No local fallback:** without an `OPENROUTER_API_KEY` there is no chat model, and the API says so clearly.

🟪Embeddings are separate from chat 🟪inference: they always come from Google's
`gemini-embedding-001` (768-dim, needs `GOOGLE_API_KEY`).

## Request flow: one chat question, start to finish (RAG mode example)

1. User types a question in `ChatInput` (apps/web); `useChat.ts` POSTs to
   `/api/v1/chat/rag` with the message history, `provider`, and optional
   `model`.
2. `app/routes/chat.py::rag_chat` calls `retrieve_relevant_chunks()`
   (`app/rag/retrieve.py`), which embeds the question (same 🟪embedding model
   used at ingest time) and queries 🟩Qdrant for the nearest 🟪chunks above a
   similarity threshold.
3. If no chunks clear the threshold, a canned "nothing relevant found"
   response is returned immediately — no 🟪LLM call, no false citations.
4. Otherwise, the 🟪retrieved chunks are formatted into a numbered context
   block (`build_context()`) and appended to the message history under a
   🟪system prompt that requires every claim to carry a `[n]` citation.
5. `app/llm/gateway.py::generate()` builds an ordered chain of models, calls them through
   🟦LiteLLM (retrying timeouts and server errors, moving straight on after a 429), times the
   call and extracts token usage from the response. See
   [the Stage 1 guide](stages/01-model-layer.md#concept-4--calling-models-safely-the-model-gateway).
6. The route returns `{ message, citations, provider, usage }` — `usage`
   is the Stage 7 telemetry object (tokens, latency, cost, fallback flag).
7. The frontend renders the answer, a citation list, a provider tag, and
   (Stage 7) a small usage footer under the message
   (`MessageBubble.tsx`).

CRM mode (`/api/v1/chat/crm`) adds one more fork before step 4: a
keyword-based classifier (`app/chat/router.py`) decides whether the
question wants structured CRM facts, document retrieval, or both, and
whichever company is named gets its retrieval scoped to that
`company_id` in Qdrant (payload filter) so citations never leak across
companies.

## Local dev vs. Docker networking

Each service has two addresses, depending on who is asking:

- From **your host machine** (a manual `curl`, the browser, `uv run` tests): `localhost` and the port Docker
  Compose maps, for example `localhost:6333` for 🟩Qdrant and `localhost:5432` for Postgres.
- From **inside the `api-py` container** (what `docker-compose.yml` sets): the compose-network DNS name and the
  service's native port: `QDRANT_URL=http://qdrant:6333` and `DATABASE_URL` pointing at `db:5432`.

## Where to look for more detail

| Topic | Where |
| --- | --- |
| Full stage-by-stage build history | [tech-stack.md](tech-stack.md) |
| API endpoints, request/response shapes | [api-reference.md](api-reference.md) |
| Frontend component/hook layering | [fe/fe-architecture-overview.md](fe/fe-architecture-overview.md) |
| Frontend chat request lifecycle | [fe/fe-chat-request-flow.md](fe/fe-chat-request-flow.md) |
| 🟪Retrieval evaluation (🟦promptfoo) suite | [../evals/README.md](../evals/README.md) |
| Local startup troubleshooting | [troubleshooting.md](troubleshooting.md) |
