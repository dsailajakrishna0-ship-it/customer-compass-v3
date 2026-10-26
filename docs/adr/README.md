# Architecture decision records (ADRs)

One short file per decision, so the reason for a choice is not buried in a long stage document.

- Name files `NNNN-short-title.md`, numbered in order. Never reuse a number; supersede instead.
- Use the template below. Keep it to one page.
- Every tool adopted or rejected in V3 gets an ADR with the **pinned version** and a link to the eval or test that justified it (see [roadmap.md](../roadmap.md)).

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-v3-goals-and-tooling-rule.md) | V3 goals and tooling rule | Accepted |

## Template

```markdown
# NNNN — Title

- **Status:** Proposed | Accepted | Superseded by NNNN
- **Date:** YYYY-MM-DD
- **Roadmap sub-stage:** e.g. 1.2

## Context
What problem or choice, and which constraints apply.

## Decision
What we chose (with pinned version).

## Alternatives considered
Short list, with why each was not chosen.

## Consequences
What gets easier, what gets harder, what to re-check later.
```
