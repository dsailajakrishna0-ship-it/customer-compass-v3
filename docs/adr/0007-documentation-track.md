# 0007 — Documentation track

- **Status:** Accepted
- **Date:** 2026-10-28
- **Roadmap sub-stage:** 0.8

## Context

V2's stage documents are hand-written implementation notes: long, text only, and frozen as a record. The project exists to *learn* concepts, and the audience is the owner first, then teammates new to AI, then a wider audience. A single big explainer written at the end would describe tools after the context that makes them make sense is gone, and would have to be redone as the stack changes.

## Decision

Two layers:

1. **Stage guides** in `docs/stages/`, one per roadmap stage, written **in the stage that introduces the concepts**, from a shared template: plain-language introduction, diagrams, worked examples from this project's data, V2 vs V3, glossary and self-check questions. A "V2 vs V3" comparison is included only when the stage replaces V2 code, configuration or tools. A stage is done only when its guide is.
2. **`docs/concepts/`**, assembled in Stage 9 from the guides: concept map, glossary, questions and answers by level, reading paths. Until then it is a placeholder that states this.

`docs/tech-stack.md` is the map: a full "at a glance" table (every tool, its purpose in plain words, the stage that adds it, its status) and a "progress by stage" table, updated in the same pull request as each stage.

Diagrams are Mermaid with one shared colour scheme; every diagram is rendered and every number checked before publishing.

## Alternatives considered

- **One concepts document written at the end:** loses context, forces rework as tools change.
- **Rewriting the frozen V2 stage docs:** they describe code that Stages 1 to 3 replace; rewriting them would explain things that are about to disappear.
- **A published documentation site:** not now. Markdown in the repo renders on GitHub and stays reviewable; a site can be generated from the same files later.

## Consequences

- Each stage PR is larger: it carries its guide and tech-stack update.
- The Stage 0 guide sets the format; later guides are reviewed against the template in `docs/stages/README.md`.
- Concept explanations live in one place per stage, so stack facts are linked, not duplicated.
