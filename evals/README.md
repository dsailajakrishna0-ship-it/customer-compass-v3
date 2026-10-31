# Evaluation

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](../docs/ai-terms.md)

## V3 baseline (sub-stage 0.7)

A fixed question set and one runner, `run_eval.py`, so every later change is measured against the seed (V2's behaviour) instead of judged by feel.

| Suite | 🟪Golden set | What is measured | Needs |
| --- | --- | --- | --- |
| `retrieval` | `golden/retrieval.json`: 36 answerable and 6 unanswerable questions over the 16 sample documents | 🟪recall@1/3/5, 🟪MRR (a document counts once, at its best rank), and the share of unanswerable questions that return nothing | stack up, documents ingested, `GOOGLE_API_KEY` |
| `tools` | `golden/tool_calls.json`: 10 cases | right 🟦MCP tool chosen, right arguments, no task written without confirmation | API and a model |
| `agent` | `golden/agent.json`: 10 cases | routing, outcome, company chosen, no task written, steps and latency | API and a model |
| `adversarial` | `adversarial-prompts.json`: 24 attacks and 6 benign 🟪prompts | attack detection rate and false positives of the rule-based guard | nothing (offline) |

```bash
just eval-offline     # adversarial suite only, no stack needed
just eval-baseline    # measure every suite and overwrite baseline/v2.json (only on purpose)
just eval             # measure again and compare with baseline/v2.json
```

`just eval` exits non-zero if any metric moves by more than its tolerance: 0 for the guard, ±0.02 for 🟪retrieval, ±0.2 for tools and 🟪agent (those depend on a sampled model). Latency and step counts are reported, never compared. `baseline/v2.json` also records the git commit, model names and 🟪embedding model it was taken with.

How to add a case: append to the matching JSON file with the next id, keep ground truth to documents that really answer the question, then re-take the baseline in the same PR and say why it changed. `tests/test_eval_baseline.py` checks the sets stay well-formed and the scoring maths is right; it runs in CI with no keys.

### Baseline results (seed code, taken 2026-10-27)

Measured on the V2 seed with a small local model (`qwen2.5:3b`; V3 sub-stage 1.3 removed local models) for chat, `gemini-embedding-001` for embeddings, 16 documents / 28 🟪chunks.

| Suite | Result |
| --- | --- |
| retrieval | recall@1 0.84, recall@3 0.99, recall@5 0.99, MRR 1.00; unanswerable questions declined by retrieval: 0 of 6 |
| tools | right tool 10/10, right arguments 10/10, no unconfirmed writes |
| agent | route, status and company all 10/10; 6 to 10 trace steps; about 41 s per case on CPU |
| adversarial | rule guard detects 11 of 24 attacks (0.46), 0 false positives |

**Read these numbers with care.**

- **Ceiling effects:** MRR, tool accuracy and agent accuracy are already at 1.0, so these sets cannot show an improvement and will only show regressions. Stage 4 (🟪hybrid search, 🟪reranking) should be judged on recall@1 and on harder questions added then.
- **Recall@1 headroom:** many questions have two or three relevant documents, so recall@1 cannot exceed 1/n for them.
- **No decline at 🟪retrieval:** the 0.45 similarity cutoff lets chunks through for all six unanswerable questions, so declining depends entirely on the model. This is the weakest spot in the seed.
- **Guard gaps:** the guard's low detection rate is real, not noise (paraphrase, encoding, indirect injection).

The known gaps are part of the result: the rule-based guard misses paraphrased, encoded and indirect injections (see `rules_catch: false` in `adversarial-prompts.json`), which Stage 5.3 compares against 🟦NeMo Guardrails and 🟧Llama Guard.

## Older promptfoo suites

The sections below describe the V2 🟦promptfoo suites, still run with `just eval-promptfoo`. They remain until Stage 5.2 adds 🟦Ragas or DeepEval next to them.

Evaluates the live `apps/api-py` 🟪RAG/CRM chat endpoints against the
`sample-data/documents` corpus, using [promptfoo](https://www.promptfoo.dev/) — an 🟪eval harness that sends test questions to the live API and grades the answers.

## What this tests

- **🟪Retrieval correctness**: does `/api/v1/chat/rag` find the right source
  document(s) for a known-answerable question, and does the generated
  answer actually reflect that source?
- **Company-scoping isolation**: a question about one company must never
  cite another company's documents.
- **Refusal behavior for out-of-corpus questions**: does the app correctly
  say "not in the sources" instead of hallucinating, for both (a) a
  question that's topically CRM-adjacent but not actually covered (refund
  policy), and (b) a completely unrelated question (geography)?
- **CRM structured facts**: does `/api/v1/chat/crm` return the right
  company/deal and scope correctly?

Each test uses **both** a deterministic check (keyword match / JS assertion
on the structured response) and an **🟪LLM-as-judge** rubric (a second, more capable free model that grades each answer) for the more
nuanced "did the answer actually make sense" grading.

## MIN_SIMILARITY tuning (PR 4 follow-up)

PR 4 flagged that `MIN_SIMILARITY=0.3` (inherited unchanged from the old
🟩pgvector/mxbai-embed-large pipeline) didn't filter unrelated questions well
with the new `gemini-embedding-001` 🟪embeddings (Google's text → vector embedding model, not a chat model). Sampling real similarity
scores against the live corpus showed a clear gap:

| Question type | Similarity range |
| --- | --- |
| Genuinely relevant (top match) | 0.69 – 0.80 |
| Genuinely relevant (other matches) | 0.50 – 0.69 |
| Plausible-but-uncovered (e.g. "refund policy") | 0.50 – 0.54 |
| Clearly unrelated (e.g. "capital of France", "bake a cake") | 0.42 – 0.44 |

`MIN_SIMILARITY` was raised from `0.3` to **`0.45`** (`apps/api-py/app/rag/retrieve.py`)
— it sits in the gap between the "clearly unrelated" and "everything else"
clusters. This **does not** fully solve the "plausible-but-uncovered"
case (those scores overlap with real matches, since they're genuinely
topically similar) — that's a known limitation of similarity-only
filtering. The 🟪LLM's own "the sources don't contain this" response text is
still the real safety net there, which is exactly what the 🟪eval suite
checks for instead of expecting zero citations in that case.

## Running

Requires the stack up (`docker compose up -d db qdrant api-py`: Postgres, 🟩Qdrant 🟪vector DB, FastAPI backend;
from the repo root), sample data already ingested
(`curl -X POST http://localhost:8001/api/v1/documents/ingest`, see the root
README if you haven't run this before), and `OPENROUTER_API_KEY` in `.env`: the app needs it to chat, and the
🟪judge model uses the same key.

```bash
cd evals
set -a; . ../.env; set +a        # makes OPENROUTER_API_KEY visible to promptfoo (the judge model uses it)
npx promptfoo@latest eval -c promptfooconfig.yaml
```

The judge model is a free 🟩OpenRouter model (`openrouter:google/gemma-4-31b-it:free` in
`defaultTest.options.provider`).

View results in an interactive browser UI:

```bash
npx promptfoo@latest view   # opens http://localhost:15500
```

This is a separate viewer from the app's UI (port 5173); `npm run dev` does
not start it. Keep the terminal open while browsing. It also works for the
Stage 8.a suite: run it after `eval -c adversarial.promptfooconfig.yaml`.

Free-tier keys only, no cost. The app under test and the judge both use free OpenRouter models, so results
vary with whichever model answers (a limit the V3 🟪evals above avoid by scoring with code).

## Known gaps / not covered yet

- No retrieval-metric scoring (precision/recall@k) — this suite checks
  end-to-end answer quality, not raw 🟪retrieval ranking in isolation.
- No regression baseline/CI wiring yet — run manually after any 🟪RAG/CRM
  🟪prompt or retrieval change.
- Only covers the 8 sample documents currently in `sample-data/documents`;
  expand `tests:` in `promptfooconfig.yaml` as more content is added.
- **🟪LLM-as-judge needs a reasonably capable model.** In V2, a 3B model as judge produced visibly
  unreliable grading (contradicted its own stated reasoning, over-literal rubric matching), and a 7B model fixed
  it. Keep the judge model separate from (and at least as capable as) the model under test.
- **Run with `-j 1` (sequential).** The default concurrency (4) can hit the free-tier rate limits (HTTP 429)
  and cause intermittent failures unrelated to retrieval quality. Use
  `npx promptfoo@latest eval -j 1 ...` for more reproducible results.
- Even sequentially, a small free model can produce a degenerate near-empty answer (e.g. just `"[1]"`)
  despite retrieving the correct 🟪chunks: a generation-quality flake, not a retrieval bug. Expect occasional
  single-test flakiness from this; rerun if a failure's citations/similarities look otherwise correct.
