# Stage 4 — Realistic CRM RAG

**Status:** Planned

## Goal

Make the assistant feel like a CRM copilot by combining structured database facts
with unstructured customer history.

## Query-routing principle

| Request type | Primary mechanism |
| --- | --- |
| Open deals above a value | SQL query |
| What a customer said about pricing | RAG retrieval |
| Deal status plus past discussions | SQL + RAG + LLM synthesis |

## Intended design requirements

- Attach customer ID, document type, date, and ownership metadata to chunks.
- Filter retrieval by customer where the question identifies an account.
- Preserve citations for unstructured claims and label structured facts clearly.
- Use conversation history carefully; query rewriting is optional and must be
  observable if introduced.

## Acceptance criteria

Answers distinguish facts fetched from PostgreSQL from claims grounded in source
documents, and never retrieve another customer’s material for a scoped question.

## Developer note

Expected files/modules for this increment:

- `db/migrations/...` — customer/document metadata indexes and any new CRM
  fields required for scoped retrieval.
- `apps/api/src/crm/queries.ts` — parameterized structured CRM queries.
- `apps/api/src/rag/retrieve.ts` — metadata filtering by customer and document
  type, extending the Stage 3 module.
- `apps/api/src/chat/router.ts` — explicit DB-only, RAG-only, and combined-query
  routing/synthesis policy.
- `apps/api/src/chat/citations.ts` — presentation of structured facts versus
  retrieved source citations.
- `apps/web/src/...` — answer sections that show facts and citations separately.

The Stage 2 general chat endpoint will be extended rather than replaced so the
development history remains easy to follow.
