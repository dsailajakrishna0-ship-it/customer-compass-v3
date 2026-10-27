# 0006 — Evaluation baseline

- **Status:** Accepted
- **Date:** 2026-10-27
- **Roadmap sub-stage:** 0.7

## Context

Stage 1 onward replaces hand-written parts with frameworks. Without numbers from the seed, "it still works" is a feeling. V2 had a promptfoo suite (about 20 cases, mostly model-graded) and a 19-prompt guard fixture, but no retrieval metrics and no tool-call or agent cases.

## Decision

- One runner, `evals/run_eval.py`, with four suites (retrieval, tools, agent, adversarial) and golden sets in `evals/golden/`; the adversarial fixture is extended from 19 to 30 prompts (24 attacks).
- **Retrieval is scored without a model judge:** recall@1/3/5 and MRR against hand-labelled relevant documents, computed from Qdrant results directly. This is cheap, repeatable, and independent of the chat model, so it stays valid when Stage 1 swaps models.
- **Tools and agent are scored by code, not by a judge:** the tool called and its arguments, the route, the status and the company chosen, plus a check that no task row was written without confirmation.
- The baseline is a committed JSON file (`evals/baseline/v2.json`) recording metrics, per-case results, git commit and model names. `just eval` re-measures and fails outside a per-suite tolerance: 0 for the deterministic guard, ±0.02 for retrieval, ±0.2 for model-dependent suites.
- Scoring maths, golden-set integrity and the comparison logic are unit-tested in CI (`tests/test_eval_baseline.py`); the live suites are not run in CI because they need keys and a model.
- The promptfoo suites stay for now (`just eval-promptfoo`); Stage 5.2 adds Ragas or DeepEval beside them.

## Alternatives considered

- **LLM-as-judge for everything:** slower, costs tokens, and the judge changes when models change. Kept only where answers cannot be scored by code (later, Stage 5.2).
- **Running the live suites in CI:** needs secrets and a sampled model, so it would be flaky; a nightly or manual run is the follow-up.
- **Bigger sets:** 42 + 10 + 10 + 30 cases is enough to see a regression on a 16-document corpus; more cases would mostly repeat the same documents.

## Consequences

- Retrieval metrics depend on the live embedding service; re-embedding with another model (Stage 4.3) changes them on purpose and needs a new baseline in the same PR.
- Tool and agent results come from a sampled model; the ±0.2 band hides small changes. Stage 1.4's typed fake model makes the logic testable without that noise.
- Ground truth was written by reading the 16 documents; it must be revisited whenever the corpus changes (Stage 4.2 ingestion, Stage 6 modules).
