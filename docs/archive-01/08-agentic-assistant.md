# Stage 8 — Agentic CRM assistant

**Status:** Planned

## Goal

Use a bounded multi-step workflow only where it creates real value: analyze an
account, retrieve supporting evidence, recommend a next action, and optionally
create a confirmed task.

## Intended flow

```text
Identify customer -> fetch CRM facts -> retrieve history -> reason -> recommend
-> ask for confirmation -> execute task tool -> audit result
```

## Design rules

- Keep simple factual questions as direct SQL or direct RAG, not agent loops.
- Prefer deterministic workflows when the action sequence is known.
- Bound tool count, time, and retries; surface intermediate evidence to users.
- Never let an agent autonomously perform important external actions without
  explicit confirmation.

## Acceptance criteria

The agent produces an evidence-backed follow-up recommendation and only creates
a task after explicit user approval. Its execution trace is inspectable.

## Developer note

Expected files/modules for this increment:

- `apps/api/src/agent/workflow.ts` — bounded orchestration state machine.
- `apps/api/src/agent/planner.ts` — optional planning/reasoning adapter with
  strict time/tool limits.
- `apps/api/src/agent/trace.ts` — inspectable evidence and tool execution trace.
- `apps/api/src/agent/policies.ts` — confirmation and stop conditions.
- `apps/api/src/tools/` — reused Stage 7 tools; no parallel action mechanism.
- `apps/web/src/...` — workflow status, evidence, recommendation, and
  confirmation experience.
- `docs/agent-boundaries.md` — decision table for direct RAG, tools,
  deterministic workflows, and agentic flows.

The agent is a composition layer over proven Stage 4 and Stage 7 capabilities;
it must not become a second implementation of retrieval, authorization, or task
creation.
