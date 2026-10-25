# Stage 5 — Retrieval quality and evaluation

**Status:** Planned

## Goal

Improve retrieval deliberately and measure it with a repeatable evaluation set
rather than relying on a few successful chat examples.

## Planned work

- Build an approximately 30-question benchmark with expected source documents.
- Add hybrid keyword + semantic retrieval where it improves results.
- Evaluate reranking, query rewriting, and multi-query retrieval only when their
  measured benefit justifies added complexity.
- Record retrieval relevance/precision/recall, answer correctness, groundedness,
  citation correctness, latency, and token consumption.

## Acceptance criteria

The repository contains an executable evaluation workflow and a baseline results
report that makes regressions visible.

## Developer note

Expected files/modules for this increment:

- `evals/questions.json` — approximately 30 versioned test questions, expected
  sources, and expected answer properties.
- `apps/api/src/rag/hybrid-search.ts` and `rerank.ts` — retrieval improvements,
  introduced only when evaluated.
- `scripts/run-evals.ts` — repeatable benchmark runner.
- `scripts/report-evals.ts` — metrics aggregation and report generation.
- `evals/results/` — timestamped, reviewable baseline outputs (excluding secrets).
- `docs/evaluation-results.md` — interpretation of metrics and trade-offs.

Do not replace the baseline retriever wholesale; preserve it as a comparison
point for each proposed quality improvement.
