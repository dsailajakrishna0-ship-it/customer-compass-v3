# Stage guides

One guide per roadmap stage, written for someone who has not seen the code. Each guide explains the **concepts that stage introduces**, with diagrams and examples from this project's own data, so you can learn the idea and see where it lives in the repo.

The [tech-stack](../tech-stack.md#v3-tech-stack-at-a-glance) lists every tool, what it is for and the stage that adds it. When all stages are done, the guides are condensed into [concepts/](../concepts/README.md): a glossary, questions and answers, and reading paths.

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](../ai-terms.md)

## Guides

| Stage | Guide | Concepts | Status |
| --- | --- | --- | --- |
| 0 | [Foundation](00-foundation.md) | CI/CD, linting and types, migrations, supply-chain security, releases, evaluation metrics | Written |
| 1 | [Model layer](01-model-layer.md) | Settings, logging and request ids (1.1); gateways, fallback, rate limits (1.2 to 1.4) | Written (1.1 to 1.4) |
| 2 | Tools and 🟦MCP | 🟪Tool calling, 🟪structured output, MCP | Written in Stage 2 |
| 3 | 🟦LangGraph port | 🟪Agent graphs, state, checkpoints, 🟪human-in-the-loop | Written in Stage 3 |
| 4 | 🟪Retrieval upgrade | 🟪Hybrid search, 🟪reranking, document parsing, 🟪embeddings | Written in Stage 4 |
| 5 | Observability and 🟪evals | Tracing, metrics beyond recall, 🟪guardrail comparison | Written in Stage 5 |
| 6 | CRM modules and auth | Authentication, authorization, schema growth | Written in Stage 6 |
| 7 | Agents and supervisor | Multi-agent routing, when an agent is worth it | Written in Stage 7 |
| 8 | Product features | Forms, uploads, end-to-end tests | Written in Stage 8 |

## The rule

A stage is not done until its guide is. Every pull request that introduces a technology or concept also:

1. adds or extends that stage's guide, and
2. updates the [tech-stack](../tech-stack.md) tables (the "at a glance" row and "progress by stage").

The pull request template has a checkbox for both.

## Who these are for

Written first for the project owner, learning the topics for the first time. They are also meant to be handed to **teammates new to AI** and, eventually, to a **wider audience**. So: plain words first, jargon defined where it first appears, and nothing assumed beyond the previous guides.

## How to write a stage guide

Use this skeleton. Keep every section except **V2 vs V3**, which is included only when the stage replaces V2 code, configuration or tools with something new. A stage that only adds a capability, or only introduces a concept, leaves that section out.

````markdown
# Stage N — Title

> **Level:** who can read it. **Reading time:** minutes. **Status:** done.
> **Roadmap:** link · **Decisions:** links to the ADRs

## In one minute
A short everyday analogy and a table mapping each analogy to the project idea.

## The big picture
One diagram of the whole stage.

## Concept 1 — Name        (repeat per concept)
- The problem it solves, in plain words.
- The idea, with the smallest example.
- A diagram (flow or sequence).
- A worked example with real numbers or cases from this project.
- A callout for a trap or a surprise we actually met.

## What this stage added to the tech stack
Table: tool, what it does in plain words, where to look in the repo.

## V2 vs V3 in this area        (only if this stage replaces something)
Before and after table: what V2 did, what V3 does now, and why it changed.

## Glossary
Terms first used here.

## Check your understanding
5 to 8 questions in `<details>` blocks, each with a short answer.

## Code tour
For code stages: a module map (diagram), a table of every **new** file (purpose, key names, who uses it), a table of **existing** files that changed and why, a suggested reading order, and the path of one request or operation through the code. Stages with no code (or only configuration) say so in one line.

**The tour is cumulative, and it shows what is new.** Each sub-stage PR extends the same tour, and the highlighting moves forward so a reader sees how the code grew:

| State | Diagram style | Table marker |
| --- | --- | --- |
| **New in this sub-stage** | bright green, thick border | 🟢 |
| **Changed in this sub-stage** (an existing module was modified) | amber | 🟡 |
| **Existing, untouched**, including everything added in earlier sub-stages | grey | ⚪ |

When sub-stage *N+1* lands:

1. In the module map (`docs/diagrams/stageN-module-map.mmd`), turn the modules from earlier sub-stages **grey**, add the new modules in **bright green** and the changed ones in **amber**, update the legend title ("state after sub-stage 1.2"), and run `just diagrams`.
2. In the tables, keep the earlier rows and change their marker to ⚪ (the "Added in" column keeps the history), then add the new rows with 🟢 or 🟡. Group them so the newest sub-stage is easy to find.
3. Append the new steps to "what happens, in order" and extend the reading order if a new module is worth reading early.

A stage's last sub-stage leaves the tour showing the whole stage; the next stage starts a new tour and diagram.

**Keep the map small.** A map that only ever adds boxes becomes unreadable, so it is redrawn, not just extended:

- **Budget:** at most about 12 boxes per module map.
- **Collapse the old:** modules from earlier sub-stages or earlier stages that this sub-stage did not touch, and that no new or changed module talks to directly, are merged into one small grey box such as "Earlier: config, logs, middleware (1.1)". Their details stay in the tables, which are never shortened.
- **Keep the context:** a collapsed module that a new or changed one depends on stays as its own grey box, so the arrow still makes sense.
- **Bright and amber stay full size**, so what is new is always the first thing you see.
- **A new stage starts fresh:** the previous stage's modules appear only as one grey "Earlier stages" box, or as the boxes the new modules connect to.

The one place everything is drawn together is at the end: the final architecture overview in the [concepts](../concepts/README.md) section and a refreshed [architecture.md](../architecture.md) (roadmap sub-stage 9.1).

## Where to look in the repo
Table of "you want to see" and the file (for stages where the code tour is not needed).

## Further reading
Official documentation only.
````

### The AI colour code

The docs mark AI terms with a coloured square before their first use in each section: 🟪 concept, 🟦 framework or tool, 🟩 data store or service, 🟧 model. Everything unmarked is ordinary software. You do **not** add the squares by hand:

1. Add or edit the term in [`ai-terms.yaml`](../ai-terms.yaml) with a plain-words meaning.
2. Run `just ai-terms`. It re-marks the target docs and regenerates the [A to Z list](../ai-terms.md).
3. Commit the result. CI fails if the docs are out of date.

A new stage guide is picked up automatically (`docs/stages/*.md` is a target). Frozen records (`v2-baseline/`, `recommendations-2.md`) and decision records (`adr/`) are not marked.

### Writing rules

- **Explain, then name.** Say what it does before you give the term.
- **Use our own data.** A worked example from the 16 sample documents beats a generic one.
- **Be honest.** Say what we measured and what we did not. Include the failures and surprises; they teach the most.
- **One idea per diagram**, no more than about ten boxes, and a sentence under it saying what to notice.
- **Teach the code, not only the idea.** Every code stage ends its concepts with a code tour, so a reader knows which file to open and in what order.
- **Link, do not copy.** Stack facts live in tech-stack.md, decisions in the ADRs.
- **Verify before you publish.** Look at every rendered image and check every number against the repo or the baseline.

### Diagram style

Diagrams are written in **Mermaid** text, kept in [`../diagrams/`](../diagrams/) (one `.mmd` file each), and **rendered to PNG images that are committed** in `docs/img/diagrams/`. The guides embed the image, so a diagram displays in every viewer: GitHub's page and diff views, editor previews, anything. (Raw Mermaid code blocks only draw where the viewer supports Mermaid, and GitHub's Mermaid version can be older than the one we test with.)

To add or change a diagram:

1. Write or edit `docs/diagrams/<name>.mmd`.
2. Run `just diagrams` (needs Docker; the first run pulls a Mermaid CLI image, pinned to 12.0.0).
3. Look at the PNG it produced in `docs/img/diagrams/`. Fix anything cramped or too wide.
4. Embed it with a descriptive alt text that says what the diagram shows, and link the source:

```markdown
![One or two sentences saying what the diagram shows.](../img/diagrams/<name>.png)

<sub>Diagram source: [<name>.mmd](../diagrams/<name>.mmd)</sub>
```

Keep diagrams narrow: if a flow has more than about five boxes in a row, wrap it into two rows with subgraphs (`direction LR` inside each, and link the subgraphs, not the inner nodes) or draw it top to bottom. Use the same colours everywhere:

| Meaning | Style |
| --- | --- |
| Done, current, success | `fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20` |
| Code tour: new in this sub-stage | `fill:#a5d6a7,stroke:#1b5e20,stroke-width:3px,color:#0d3b12` |
| Code tour: changed in this sub-stage | `fill:#fff3cd,stroke:#f9a825,stroke-width:2px,color:#5d4037` |
| Code tour: existing, untouched | `fill:#eceff1,stroke:#b0bec5,color:#78909c` |
| Data stores | `fill:#e3f2fd,stroke:#1976d2,color:#0d47a1` |
| Planned, future | `fill:#eceff1,stroke:#607d8b,color:#263238` |
| Problem, blocked, failure | `fill:#ffebee,stroke:#c62828,color:#b71c1c` |

```text
classDef ok fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
classDef store fill:#e3f2fd,stroke:#1976d2,color:#0d47a1
classDef plan fill:#eceff1,stroke:#607d8b,color:#263238
classDef bad fill:#ffebee,stroke:#c62828,color:#b71c1c
```

Use `flowchart` for how things connect, `sequenceDiagram` for who talks to whom in order. Callouts use GitHub's `> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`, `> [!WARNING]`.
