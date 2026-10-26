# 0001 — V3 goals and tooling rule

- **Status:** Accepted
- **Date:** 2026-10-26
- **Roadmap sub-stage:** 0.2

## Context

V2 (Stages 1–10) was hand-built on purpose to learn the mechanics of RAG, guardrails, tool calling and agents. It is closed and tagged `v2-final` in `customer-compass-v2`. V3 is a learning project with no paid budget, and its goal shifts to how widely used open-source frameworks and tools replace hand-written plumbing, and what else the product can do.

## Decision

1. **Frameworks replace hand-written code in V3.** V2 remains the baseline for comparison; each replacement records before/after results in an ADR.
2. **Tooling rule:** frameworks and tooling must be open source. Model APIs may be free-tier hosted. Model access stays behind one interface so a local open-weights model can be added later.
3. **Cloud models only, free tiers only.** Free models rate-limit and change, so model lists are configuration, calls retry with backoff, and CI uses mocked models.
4. **Orchestration is LangGraph** (decided in the roadmap revision of 2026-10-25). Other agent frameworks are compared only with a specific reason.
5. **Evidence before change:** a baseline evaluation set is built before the first port (sub-stage 0.7), and each stage must stay within agreed tolerance of it.
6. **Safety rules do not change:** every write stays behind human confirmation, the guardrails and the audit log.
7. Verify each tool's current version, licence and free-tier limits on its own page before adopting it, and pin the version.

## Alternatives considered

- Keep hand-building everything: rejected, V2 already covered the fundamentals.
- Allow paid APIs: rejected, no budget and it would hide rate-limit and fallback lessons.
- Several agent frameworks side by side in the main path: rejected, overlapping tools obscure what each teaches. A throwaway comparison branch is allowed.

## Consequences

- Stage 1 removes Ollama and local inference; offline development is no longer possible.
- Each tool adoption costs one short ADR, which keeps decisions findable.
- Free-tier changes can break live evals, so record-and-replay and mocked CI are required (roadmap Stages 0.4 and 1).
