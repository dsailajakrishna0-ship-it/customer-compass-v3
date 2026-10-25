# Stage 7 — Tool calling

**Status:** Planned

## Goal

Let the LLM request constrained application operations through validated tool
schemas instead of attempting to invent or directly execute actions.

## Candidate tools

- Customer lookup/search
- Deal and interaction lookup
- Knowledge search
- Support-case lookup
- Email drafting
- Follow-up task creation

## Design rules

Read operations can be performed after authorization. Mutating operations such
as task creation require schema validation, access checks, error handling, audit
logging, and user confirmation before execution.

## Acceptance criteria

For a request such as “show the current deal and summarize recent discussions,”
the model selects database and retrieval tools. For “create a follow-up task,”
it presents a proposed action and waits for confirmation.

## Developer note

Expected files/modules for this increment:

- `apps/api/src/tools/definitions.ts` — typed tool schemas and descriptions.
- `apps/api/src/tools/customer.ts`, `deal.ts`, `knowledge.ts`, and `task.ts` —
  independently validated tool implementations.
- `apps/api/src/tools/dispatcher.ts` — authorization, validation, and safe
  execution boundary.
- `apps/api/src/chat/tool-loop.ts` — limited model/tool orchestration.
- `db/migrations/...` — task table and tool/audit records if not introduced
  earlier.
- `apps/web/src/...` — proposed-action review and explicit confirmation UI.

Tool functions must call existing CRM/RAG modules; they must not duplicate SQL or
retrieval logic in the model orchestration layer.
