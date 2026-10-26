# Customer Compass docs

Start here. The repo is the V3 learning project, seeded from `customer-compass-v2` (tag `v2-final`). Documents are grouped by what you want to do.

## Plan and decisions

| Document | What it is |
| --- | --- |
| [roadmap.md](roadmap.md) | The V3 plan: stages 0–9, sub-stages, tasks and exit criteria. Status of each stage is tracked here. |
| [recommendations-2.md](recommendations-2.md) | Implementation reference: findings on the V2 docs and code (D, R IDs), the tooling table (T1–T18), diagrams and risks. Frozen snapshot. |
| [adr/](adr/README.md) | One short decision record per tool or design choice, with pinned versions. |

## Understand the system

| Document | What it is |
| --- | --- |
| [architecture.md](architecture.md) | How the pieces fit together, request flow, and the stage-by-stage build-up. |
| [tech-stack.md](tech-stack.md) | **Single source of truth** for the technology in use, what each replaced, and free alternatives. |
| [api-reference.md](api-reference.md) | Every HTTP endpoint, request and response shape, error shape. |
| [agent-boundaries.md](agent-boundaries.md) | Which pattern to use for which question (SQL, RAG, tool calling, workflow, agents). |
| [fe/](fe/fe-architecture-overview.md) | Frontend layering and the chat request lifecycle. |

## Run and test

| Document | What it is |
| --- | --- |
| [testing-guide.md](testing-guide.md) | Commands to start everything, URLs to open, chat modes and sample questions, curl checks. |
| [troubleshooting.md](troubleshooting.md) | Known local-startup issues and how to use the chat panel. |
| [../evals/README.md](../evals/README.md) | The promptfoo evaluation suites. |

## Learning record (V2 baseline)

[v2-baseline/](v2-baseline/README.md) holds the frozen Stage 1–10 documents: how each part was hand-built in V2, with the goal, scope, acceptance criteria and honest limits. They are the "before" that V3 stages compare against.

## Conventions

- Stack facts (versions, models, providers) live in [tech-stack.md](tech-stack.md) only; other documents link to it.
- Decisions live in [adr/](adr/README.md), not in stage prose.
- Use repo-relative paths in docs, never absolute paths from a local machine.
- Update the affected docs in the same PR that changes behaviour.
- The synthetic CRM data in this repo is original and does not reproduce any existing CRM product.
