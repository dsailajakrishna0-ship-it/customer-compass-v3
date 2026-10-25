# Stage 7 — Production-style concerns

**Part:** III — Trust & Safety
**Status:** Done (PR #8, `feature/stage-7-production-concerns`)

## What this stage actually covers

The original plan below (kept further down for context) scoped this stage
much more broadly — auth, authorization-scoped retrieval, audit logging,
rate limiting. After discussing scope before building, we deliberately
narrowed Stage 7 to the two concrete problems that actually came up during
manual testing of earlier stages:

1. **A cloud provider failure shouldn't be a dead end.** OpenRouter's (gateway to hosted cloud models) free
   tier rate-limits/rotates models often; a single failed request used to
   surface a flat 503 with no recovery path.
2. **We had no visibility into what each answer actually cost** in tokens,
   latency, or (eventually) money — important context once you're
   comparing providers/models, which this project already lets you do
   per-request.

The broader items (auth, authorization-aware retrieval, audit trail, rate
limiting) remain **out of scope / deferred** — see
["Deferred: the original broader scope"](#deferred-the-original-broader-scope)
below. This project's learning goal here was "make provider failures
visible and recoverable, and make cost/latency observable," not build a
production auth system.

## What was built

1. **Automatic cross-provider fallback** (`app/llm/provider.py`). If the
   requested provider (`cloud` or `ollama` — the local model runner) raises — timeout, rate-limit,
   invalid model, provider outage — `generate()` retries once with the
   *other* provider before giving up. The response is flagged
   (`usage.fallbackUsed` / `usage.fallbackFrom`) so this is visible, not
   silent. If both providers fail, the original error is raised (still
   surfaced as an HTTP 503, see [api-reference.md](../api-reference.md)).

2. **Per-request telemetry** (`app/llm/types.py::GenerationResult`). Every
   provider call now returns the actual provider/model used, input/output
   token counts (from the provider's own response — `prompt_eval_count`/
   `eval_count` for Ollama, `usage.*` for OpenRouter), latency in
   milliseconds, and an estimated cost (`$0` today, since every model the
   UI currently offers is free-tier; `cloud.py` has a per-model price map
   ready for when paid models are enabled).

3. **Surfaced in two places**: logged server-side (`llm_usage` log line in
   `app/routes/chat.py`) and returned to the frontend in a `usage` object
   on every `/api/v1/chat*` response, rendered as a small footer under each
   chat answer (`MessageBubble.tsx`) — model name, latency, tokens, cost,
   plus a visible orange warning line when fallback was used.

4. **Bonus fix found along the way** (actually landed in PR #7, just
   before this stage, but directly related): FastAPI's default error body
   is `{"detail": ...}`, while the frontend's contract (ported from the
   old Express API) reads `{"error": ...}` — so real backend errors (like
   the OpenRouter rate-limit messages this stage is designed to recover
   from) were silently showing as a generic "Something went wrong." in the
   UI. Fixed with a global exception handler in `app/main.py` that returns
   both keys.

See the [API reference's Usage object section](../api-reference.md#usage-object-stage-7)
for the exact response shape, and
[architecture.md](../architecture.md#request-flow-one-chat-question-start-to-finish-rag-mode-example)
for how this fits into the overall request flow.

## How to run the app

```bash
cd /home/devarapallim/Murali/git-personal/customer-compass-v2
docker compose up -d db qdrant ollama api-py
cd apps/web && npm run dev
```

## How to test manually

1. **Normal path, both providers**: ask any question via Cloud and via
   Local (Ollama) in the UI — confirm a small usage footer appears under
   each answer (model · latency · tokens · cost), and no fallback warning.
2. **Forced fallback**:
   ```bash
   curl -X POST http://localhost:8001/api/v1/chat/rag \
     -H 'Content-Type: application/json' \
     -d '{"messages":[{"role":"user","content":"test"}],"provider":"cloud","model":"not-a-real-model"}'
   ```
   Expect **HTTP 200** (not 503) with a real answer and
   `usage.fallbackUsed: true`, `usage.provider: "ollama"`,
   `usage.fallbackFrom: "cloud"`.
3. **Real-world fallback**: if a free OpenRouter model is actually
   rate-limited at the moment you ask, confirm the UI shows the orange
   "⚠ Cloud (OpenRouter) was unavailable — answered via Local (Ollama)
   instead." line, rather than an error.
4. **Error surfacing still works**: with no reachable fallback (e.g. stop
   the `ollama` container and force a cloud failure), confirm the chat
   shows the real OpenRouter error message, not "Something went wrong."

## Developer note

Files touched for this increment:
- `apps/api-py/app/llm/types.py` — `GenerationResult` dataclass.
- `apps/api-py/app/llm/cloud.py`, `apps/api-py/app/llm/ollama.py` — return
  `GenerationResult` instead of a plain string; extract usage/latency.
- `apps/api-py/app/llm/provider.py` — fallback retry logic.
- `apps/api-py/app/routes/chat.py` — `_usage_json()` helper, logging,
  `usage` field on all three chat responses.
- `apps/web/src/types/index.ts` — `ChatUsage` type.
- `apps/web/src/hooks/useChat.ts`, `apps/web/src/components/chat/MessageBubble.tsx`,
  `apps/web/src/styles.css` — usage footer rendering.

---

## Deferred: the original broader scope

The paragraphs below are the original Stage 7 plan, kept for reference in
case this project picks up a real auth/authorization/audit pass later (it
would be a substantial, separate piece of work — likely its own stage
rather than a Stage 7 addendum).

### Scope categories

| Category | Planned focus |
| --- | --- |
| Must have | basic authentication, authorization-aware retrieval, audit events, safe errors |
| Nice to have | rate limiting, caching, structured logs, request tracing |
| Enterprise extension | document versioning, incremental indexing, stale-content workflows |

### Security focus

Document metadata and retrieval filters must enforce user/customer access.
Untrusted content handling and prompt-injection defense are treated in depth in
Stage 8; this stage establishes the authorization/audit boundary they build on.
PII is identified and handled deliberately in logs and prompts.

### Acceptance criteria (original)

The application demonstrates one protected access path, records auditable AI
operations, and has documented boundaries for features deliberately deferred.

### Expected files/modules (original plan, not built)

- `apps/api-py/app/auth/` — identity extraction and authorization middleware.
- `apps/api-py/app/security/` — prompt-input handling and PII/logging policy.
- `apps/api-py/app/audit/` — audit-event model and writer.
- `apps/api-py/app/observability/` — structured request/model/retrieval logging.
- `apps/api-py/app/middleware/` — error responses and rate limiting.
- `db/migrations/...` — users/roles, document ACLs, and audit records as needed.
- `docs/security-model.md` — explicitly documented permissions and deferred
  enterprise extensions.

(Stage 9 later added a narrower `tool_audit_log` table (a Postgres table recording each MCP tool call) for MCP tool calls;
see [09-tool-calling-mcp.md](../part-4-autonomy-protocols/09-tool-calling-mcp.md).)
