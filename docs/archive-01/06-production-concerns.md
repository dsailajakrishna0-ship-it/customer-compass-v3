# Stage 6 — Production-style concerns

**Status:** Planned

## Goal

Add the smallest set of controls that makes the demonstration credible without
turning a learning project into an enterprise platform.

## Scope categories

| Category | Planned focus |
| --- | --- |
| Must have | basic authentication, authorization-aware retrieval, audit events, safe errors |
| Nice to have | rate limiting, caching, structured logs, request tracing |
| Enterprise extension | model fallback, document versioning, incremental indexing, stale-content workflows |

## Security focus

Document metadata and retrieval filters must enforce user/customer access. Prompt
injection content is treated as untrusted data, never as instructions. PII is
identified and handled deliberately in logs and prompts.

## Acceptance criteria

The application demonstrates one protected access path, records auditable AI
operations, and has documented boundaries for features deliberately deferred.

## Developer note

Expected files/modules for this increment:

- `apps/api/src/auth/` — identity extraction and authorization middleware.
- `apps/api/src/security/` — prompt-input handling and PII/logging policy.
- `apps/api/src/audit/` — audit-event model and writer.
- `apps/api/src/observability/` — structured request/model/retrieval logging.
- `apps/api/src/middleware/` — error responses and rate limiting.
- `db/migrations/...` — users/roles, document ACLs, and audit records as needed.
- `docs/security-model.md` — explicitly documented permissions and deferred
  enterprise extensions.

Existing retrieval APIs must receive authorization context rather than relying on
the UI alone to restrict visible customers.
