# Stage guides

One guide per roadmap stage, written for someone who has not seen the code. Each guide explains the **concepts that stage introduces**, with diagrams and examples from this project's own data, so you can learn the idea and see where it lives in the repo.

The [tech-stack](../tech-stack.md#v3-tech-stack-at-a-glance) lists every tool, what it is for and the stage that adds it. When all stages are done, the guides are condensed into [concepts/](../concepts/README.md): a glossary, questions and answers, and reading paths.

## Guides

| Stage | Guide | Concepts | Status |
| --- | --- | --- | --- |
| 0 | [Foundation](00-foundation.md) | CI/CD, linting and types, migrations, supply-chain security, releases, evaluation metrics | Written |
| 1 | Model layer | Settings, model gateways, fallback, rate limits | Written in Stage 1 |
| 2 | Tools and MCP | Tool calling, structured output, MCP | Written in Stage 2 |
| 3 | LangGraph port | Agent graphs, state, checkpoints, human-in-the-loop | Written in Stage 3 |
| 4 | Retrieval upgrade | Hybrid search, reranking, document parsing, embeddings | Written in Stage 4 |
| 5 | Observability and evals | Tracing, metrics beyond recall, guardrail comparison | Written in Stage 5 |
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

## Where to look in the repo
Table of "you want to see" and the file.

## Further reading
Official documentation only.
````

### Writing rules

- **Explain, then name.** Say what it does before you give the term.
- **Use our own data.** A worked example from the 16 sample documents beats a generic one.
- **Be honest.** Say what we measured and what we did not. Include the failures and surprises; they teach the most.
- **One idea per diagram**, no more than about ten boxes, and a sentence under it saying what to notice.
- **Link, do not copy.** Stack facts live in tech-stack.md, decisions in the ADRs.
- **Verify before you publish.** Render every diagram and check every number against the repo or the baseline.

### Diagram style

Mermaid, so diagrams live in the markdown and are reviewed like code. Use the same colours everywhere:

| Meaning | Style |
| --- | --- |
| Done, current, success | `fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20` |
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
