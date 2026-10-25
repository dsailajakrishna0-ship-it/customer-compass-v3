# Stage 5 — Realistic CRM RAG

**Part:** II — Grounded Intelligence
**Status:** Implemented

> **v2 stack note:** file paths below (`apps/api/src/*.ts`) and URLs are from
> the original Express API. Current equivalents: `apps/api-py/app/crm/queries.py`,
> `app/chat/router.py` (the query router that picks DB facts, documents, or both), `app/rag/retrieve.py`, `app/routes/chat.py`, served at
> `http://localhost:8001/api/v1/chat/crm`. `chat/citations.ts` was not ported
> (citation shaping lives in `routes/chat.py`). Tests: `cd apps/api-py && uv run pytest`.

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

## How to run the app

```bash
cd /home/devarapallim/Murali/git-personal/customer-compass
docker compose up -d db ollama
npm install
npm run dev
```

Ensure Stage 3 documents are ingested (`POST /api/documents/ingest`) so
customer-scoped retrieval has data to filter.

## How to test manually

1. **DB-only question**
   Ask "What open deals does Acme Fabrication have?" and confirm the answer
   comes from a direct SQL lookup (structured facts, no citations).
2. **RAG-only question**
   Ask "What did Ravi say about the volume discount?" and confirm the answer
   is grounded with citations to the matching interaction document.
3. **Combined SQL + RAG question**
   Ask "What's the status of Acme's renewal deal, and what have we discussed
   with them recently?" and confirm the response clearly separates the
   structured deal fact from the cited discussion summary.
4. **Customer-scoping boundary**
   Ask a question naming one company (e.g. Acme) and confirm the retrieved
   citations only ever reference that company's documents, never another
   company's, even when phrasing is ambiguous.
5. **Browser walkthrough** — in the chat panel, confirm the UI visibly
   separates "facts" (from the database) from "citations" (from retrieved
   documents) rather than blending them into one undifferentiated answer.

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

## Actual implementation

No new migration or table was needed — `documents.company_id` already existed
from Stage 3 ingestion, so customer-scoping could build directly on it.

- `apps/api/src/crm/queries.ts` — `listCompanies()`, `getOpenDeals(companyId)`,
  `getCompanySummary(companyId)` (industry, relationship status, open deals,
  won/lost counts). Plain parameterized SQL, no embeddings or LLM calls.
- `apps/api/src/chat/router.ts` — `classifyQuery(question)`, a deterministic
  keyword-based classifier (not an LLM call, by design, so routing stays fast
  and observable): structured keywords (deal, pipeline, amount, status of,
  close date, revenue, won, lost, …) set `wantsStructured`; discussion
  keywords (said, mentioned, email, call, note, feedback, …) set `wantsRag`;
  if neither matches, it falls back to RAG-only, preserving Stage 3 behavior.
  A company is "detected" when a significant word (>3 chars) from a known
  company name appears in the question, which also drives customer-scoping.
- `apps/api/src/rag/retrieve.ts` — `retrieveRelevantChunks()` gained an
  optional `companyId` parameter; the SQL filters to
  `company_id = $companyId OR company_id IS NULL`, so a scoped question only
  ever surfaces that company's own documents plus company-agnostic ones
  (e.g. product overviews) — never another company's material.
- `apps/api/src/routes/chat.ts` — new, additive `POST /api/chat/crm` endpoint.
  It runs `classifyQuery`, conditionally fetches `getCompanySummary` and/or
  scoped RAG chunks, and builds a prompt with a "Verified CRM facts (already
  correct, do not cite)" block and a "Source documents" (numbered, `[n]`
  citation) block. The existing `/` and `/rag` endpoints are untouched.
- `apps/web/src/main.tsx` — the RAG checkbox became a three-way "Chat mode"
  dropdown (General / Document knowledge (RAG) / CRM copilot). Switching
  modes resets the conversation (same pattern as the Stage 4 RAG-toggle
  fix, generalized). CRM-mode responses render a distinct "Facts (from CRM
  database)" panel above the usual numbered citations list.

## How to test manually (verified)

All 5 scenarios below were run against `qwen2.5:3b` via `POST /api/chat/crm`:

1. "What deals does Acme Fabrication have in the pipeline?" → facts populated
   (one open deal, amount, close date), `citations: []`.
2. "What did Acme Fabrication say about onboarding in their emails?" →
   `facts: null`, 4 numbered citations, all `[n]`-referenced in the answer.
3. "What deals does Acme Fabrication have, and what did they say about
   onboarding emails?" → both facts and citations present, answer clearly
   separates the deal fact from the cited discussion.
4. "What did Northstar Logistics say about onboarding in their emails?" →
   `scopedCompany: "Northstar Logistics"`; all returned citations belong to
   Northstar or are company-agnostic — none from Acme or Harbor & Pine.
5. Browser UI: the "Facts (from CRM database)" block renders visibly above
   the citations list and is only shown for CRM-mode messages that returned
   facts.

`cd apps/api && npm test` (6/6 passing) and `npx tsc --noEmit` in both
`apps/api` and `apps/web` confirm no regressions.
