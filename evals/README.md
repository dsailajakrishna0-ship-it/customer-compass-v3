# Retrieval Evaluation (Stage 6)

Evaluates the live `apps/api-py` RAG/CRM chat endpoints against the
`sample-data/documents` corpus, using [promptfoo](https://www.promptfoo.dev/) — an eval harness that sends test questions to the live API and grades the answers.

## What this tests

- **Retrieval correctness**: does `/api/v1/chat/rag` find the right source
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
on the structured response) and an **LLM-as-judge** rubric (a second model, `qwen2.5:7b`, that grades each answer) for the more
nuanced "did the answer actually make sense" grading.

## MIN_SIMILARITY tuning (PR 4 follow-up)

PR 4 flagged that `MIN_SIMILARITY=0.3` (inherited unchanged from the old
pgvector/mxbai-embed-large pipeline) didn't filter unrelated questions well
with the new `gemini-embedding-001` embeddings (Google's text → vector embedding model, not a chat model). Sampling real similarity
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
filtering. The LLM's own "the sources don't contain this" response text is
still the real safety net there, which is exactly what the eval suite
checks for instead of expecting zero citations in that case.

## Running

Requires the full stack up (`docker compose up -d db qdrant ollama api-py` — Postgres, Qdrant vector DB, Ollama local model runner, FastAPI backend;
from the repo root) with sample data already ingested
(`curl -X POST http://localhost:8001/api/v1/documents/ingest`, see the root
README if you haven't run this before).

```bash
cd evals
OLLAMA_BASE_URL=http://localhost:11435 npx promptfoo@latest eval -c promptfooconfig.yaml
```

(`OLLAMA_BASE_URL` points promptfoo's LLM-as-judge at this project's Ollama
container, which is mapped to host port 11435, not the default 11434.)

The judge model (`ollama:chat:qwen2.5:7b` in `defaultTest.options.provider`)
needs to be pulled once:

```bash
docker exec customer-compass-v2-ollama ollama pull qwen2.5:7b
```

View results in an interactive browser UI:

```bash
npx promptfoo@latest view   # opens http://localhost:15500
```

This is a separate viewer from the app's UI (port 5173); `npm run dev` does
not start it. Keep the terminal open while browsing. It also works for the
Stage 8.a suite: run it after `eval -c adversarial.promptfooconfig.yaml`.

No API keys or cloud cost required — both the app under test and the judge
model run on the local Ollama instance.

## Known gaps / not covered yet

- No retrieval-metric scoring (precision/recall@k) — this suite checks
  end-to-end answer quality, not raw retrieval ranking in isolation.
- No regression baseline/CI wiring yet — run manually after any RAG/CRM
  prompt or retrieval change.
- Only covers the 8 sample documents currently in `sample-data/documents`;
  expand `tests:` in `promptfooconfig.yaml` as more content is added.
- **LLM-as-judge needs a reasonably capable model.** `qwen2.5:3b` as judge
  produced visibly unreliable grading (contradicted its own stated
  reasoning, over-literal rubric matching). Switching the judge to
  `qwen2.5:7b` fixed this. Keep the judge model separate from (and at
  least as capable as) the model under test.
- **Run with `-j 1` (sequential).** The default concurrency (4) overloads
  the single local Ollama instance handling both embeddings/generation
  for the app under test, causing real intermittent `503`s unrelated to
  retrieval quality. Use `npx promptfoo@latest eval -j 1 ...` for
  reliable, reproducible results.
- Even sequentially, the small local generation model (`qwen2.5:3b`,
  configured as the app's own `LLM_PROVIDER=ollama` default) occasionally
  produces a degenerate near-empty answer (e.g. just `"[1]"`) despite
  retrieving the correct chunks — a generation-quality flake, not a
  retrieval bug. Expect occasional single-test flakiness from this; rerun
  if a failure's citations/similarities look otherwise correct.
