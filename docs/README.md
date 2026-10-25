# Customer Compass development guide

This folder is the durable engineering record for the learning project. Read the
stage documents in order; each stage has a working boundary and must be verified
before the next stage changes its assumptions.

Stages are grouped into **Parts** so the roadmap stays navigable as new topics
are added. Each part is its own folder; new parts can be appended later without
disrupting earlier ones.

## Part I — Foundations
*Get a working CRM + basic AI loop running locally.*

| Stage | Status | Document |
| --- | --- | --- |
| 1. CRM foundation | Complete | [01-foundation.md](part-1-foundations/01-foundation.md) |
| 2. First local LLM chat | Complete | [02-first-llm-chat.md](part-1-foundations/02-first-llm-chat.md) |
| 3. Basic RAG | Complete | [03-basic-rag.md](part-1-foundations/03-basic-rag.md) |

## Part II — Grounded Intelligence
*Make answers accurate, realistic, and provider-flexible.*

| Stage | Status | Document |
| --- | --- | --- |
| 4. Cloud LLM provider option | Complete | [04-cloud-llm-provider.md](part-2-grounded-intelligence/04-cloud-llm-provider.md) |
| 5. Realistic CRM RAG | Complete | [05-realistic-crm-rag.md](part-2-grounded-intelligence/05-realistic-crm-rag.md) |
| 6. Retrieval evaluation | Complete | [06-retrieval-evaluation.md](part-2-grounded-intelligence/06-retrieval-evaluation.md) |

## Part III — Trust & Safety
*Make it credible and safe before adding autonomy.*

| Stage | Status | Document |
| --- | --- | --- |
| 7. Production concerns | Complete | [07-production-concerns.md](part-3-trust-safety/07-production-concerns.md) |
| 8. Prompt-injection defense & guardrails (incl. 8.a adversarial set, 8.b output guard, 8.c audit log, 8.d LLM classifier, 8.e coverage map) | Complete | [08-prompt-injection-guardrails.md](part-3-trust-safety/08-prompt-injection-guardrails.md) |

## Part IV — Autonomy & Protocols
*Let the assistant act, using modern standards.*

| Stage | Status | Document |
| --- | --- | --- |
| 9. Tool calling via MCP | Complete | [09-tool-calling-mcp.md](part-4-autonomy-protocols/09-tool-calling-mcp.md) |
| 10. Agentic CRM assistant (Account Follow-up Recommender) | Complete | [10-agentic-assistant.md](part-4-autonomy-protocols/10-agentic-assistant.md) |

## Baseline stack

- Frontend: React + Vite + TypeScript (the browser chat UI)
- Backend: FastAPI + Python (the API that routes chat requests, calls the models and queries the data; migrated from the original Express/TypeScript
  API during the v2 stack migration — see [architecture.md](architecture.md))
- Relational data: PostgreSQL 17 in Docker (the CRM tables; `pgvector` is not used in v2)
- Vector storage: Qdrant in Docker (a vector database holding document chunk embeddings for similarity search)
- Embeddings: Google `gemini-embedding-001` (768-dim, requires
  `GOOGLE_API_KEY`; an embedding model that turns text into vectors — not a chat model)
- Local inference: Ollama + Qwen2.5 3B in Docker (Ollama runs the local *generating* model that writes the chat answers; chat/completion only)
- Tool calling (Stage 9): MCP (a protocol that exposes tools to the model) server over stdio (`apps/api-py/app/mcp/`)
- Cloud inference (Stage 4+): OpenRouter (gateway to hosted cloud generating models), swappable via configuration or
  per-request

This is an intentionally small, original CRM. It uses only synthetic data and
does not reproduce an existing CRM product.

See [conversation-progress.md](conversation-progress.md) for a concise running
record of the original (v1, Stages 1–3) decisions, and
[project-history-reference.md](project-history-reference.md) for the
narrative through Stage 9. [v3-roadmap-draft.md](v3-roadmap-draft.md) holds
non-binding future planning notes.

> **Historical-docs note:** the Stage 1–6 documents were written against the
> original Express/TypeScript API (`apps/api`, port 3001, `/api/...`). The v2
> stack serves FastAPI on port 8001 under `/api/v1/...` — each of those
> documents carries a banner mapping old paths/commands to the current ones.

See [tech-stack.md](tech-stack.md) for a cross-cutting reference of the
active technology per capability (LLM inference, embeddings, vector storage,
tool calling, guardrails, evaluation), what alternatives are already wired in
as opt-in toggles, and other free options worth exploring — updated as new
stages introduce new choices.

See [architecture.md](architecture.md) for the system-level "how it all fits
together" diagram (frontend/backend/Postgres/Qdrant/LLM providers, request
flow, local-vs-Docker networking) and [api-reference.md](api-reference.md)
for every HTTP endpoint's request/response shape, including the Stage 7
usage/telemetry object and the shared error shape.

## Testing guide

See [testing-guide.md](testing-guide.md) for the single "how do I actually
try this" doc: commands to start everything, URLs to open/monitor, every
chat-mode × provider dropdown combination with sample questions and
expected results, and quick curl-only checks for isolating UI vs. backend
bugs. For a guided path through all ten stages in an Ask / Observe / Learn
pattern, see [v2-testing-walkthrough.md](v2-testing-walkthrough.md).

## Usage guide & troubleshooting

See [v2-startup-troubleshooting.md](v2-startup-troubleshooting.md) for how to
use the "Ask Compass" chat panel (modes, models, example questions) plus
known local-startup issues specific to this repo (container-name clashes
with v1, shared ports, env-file setup, free-tier cloud model quirks) and how
to work around them.

## Archive

[`archive-01/`](archive-01/) contains a frozen snapshot of the original flat
8-stage numbering, kept for history. It is not maintained going forward — use
the Part-based index above.

## Developer note

Keep this index updated whenever a stage changes from Planned to Complete, its
implementation scope changes, or a new stage/part is added. Every stage document
includes a **How to run the app** and **How to test manually** section — the
manual steps are independent of (and in addition to) any automated test suite.
