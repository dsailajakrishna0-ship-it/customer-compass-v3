# 0011 — Streaming answers (SSE): deferred

- **Status:** Accepted
- **Date:** 2026-10-31
- **Roadmap sub-stage:** 1.4

## Context

Chat answers arrive all at once, after the whole model reply is finished. Streaming (Server-Sent Events, **SSE**) would show words as they are produced, which feels faster, especially with slow free models. The roadmap asked for a decision, not necessarily an implementation.

What the answer path does after the model replies:

- **Output guardrails** inspect the *complete* text (leaked prompts, secrets, unsafe content). Text already sent to the browser cannot be taken back.
- **Citations and the facts used** are assembled and checked after generation, then attached to the response.
- **Tool and agent modes** make several model calls per request; only the last reply is an answer, and the agent returns a structured trace and a proposed task, not prose.
- The web app, the API reference, the eval runner and the tests all expect one JSON response.

## Decision

**Do not stream yet.** Keep one JSON response per request.

The gateway ([ADR 0009](0009-litellm-gateway.md)) is the only place that talks to models, and LiteLLM supports streaming, so adding it later is a contained change: a streaming variant of `generate()`, one route, one hook in the web app. Nothing built now makes it harder.

**Revisit when any of these is true:**

1. Measured chat latency on hosted models (see [ADR 0012](0012-agent-limits.md)) is regularly long enough that users wait visibly (a few seconds before any text).
2. The output guardrails can work on partial text (for example a streaming-safe filter), or the decision is made to show text first and retract it on a violation.
3. A second client (not the web app) needs incremental output.

## Alternatives considered

- **Stream everything now:** weakens the output guard (text leaves before it is checked) and forces the citation, facts and agent paths into a second shape.
- **Stream plain chat only, buffer the rest:** two behaviours to test and explain for a latency gain nobody has measured yet.
- **Fake streaming (reveal the finished text gradually in the browser):** looks like streaming and has none of its benefit; it would only hide the real wait.

## Consequences

- Slow models mean a wait with no text; the web app shows a "thinking" state, nothing more.
- No new moving parts in Stage 1; the guard and citation guarantees stay simple to state.
- Re-open this ADR with measured numbers, not impressions.
