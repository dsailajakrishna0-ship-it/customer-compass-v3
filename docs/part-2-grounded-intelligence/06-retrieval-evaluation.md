# Stage 6 — Retrieval quality and evaluation

**Part:** II — Grounded Intelligence
**Status:** Implemented

The delivered suite is a **promptfoo** evaluation (an eval harness that sends test questions to the live API and grades the answers) of the live `/api/v1/chat/rag`
and `/api/v1/chat/crm` endpoints (deterministic checks plus an LLM-as-judge
rubric, i.e. a second model that grades the answers). Full documentation, including how to run it and its known gaps, lives
in [../../evals/README.md](../../evals/README.md); the config is
[`evals/promptfooconfig.yaml`](../../evals/promptfooconfig.yaml).

## Goal

Improve retrieval deliberately and measure it with a repeatable evaluation set
rather than relying on a few successful chat examples.

## What was built

- A promptfoo test suite covering per-company grounding, company-scoping
  isolation, out-of-corpus refusal, and CRM structured-fact correctness.
- An LLM-as-judge rubric (`ollama:chat:qwen2.5:7b`, the local judge model, bigger than the `qwen2.5:3b` generating model) alongside deterministic
  `icontains`/JavaScript assertions in the same test cases.
- Empirical tuning of `MIN_SIMILARITY` in `apps/api-py/app/rag/retrieve.py`
  (`0.3` → `0.45`), documented in the evals README.

## Not built (deferred)

- The ~30-question benchmark with expected source documents, retrieval
  precision/recall metrics, and a baseline results report.
- Hybrid keyword + semantic retrieval, reranking, query rewriting and
  multi-query retrieval.
- Local-vs-cloud provider comparison runs.

## How to run the app

```bash
cd /home/devarapallim/Murali/git-personal/customer-compass-v2
docker compose up -d db qdrant ollama api-py
docker exec customer-compass-v2-ollama ollama pull qwen2.5:7b   # judge model, once
curl -X POST http://localhost:8001/api/v1/documents/ingest      # once
```

## How to test manually

1. **Run the suite**
   ```bash
   cd evals
   OLLAMA_BASE_URL=http://localhost:11435 npx promptfoo@latest eval -j 1 -c promptfooconfig.yaml
   ```
2. **Inspect results**: `npx promptfoo@latest view`.
3. **Regression check**: lower `MIN_SIMILARITY` in `retrieve.py`, rebuild
   `api-py` (`docker compose up -d --build api-py`), re-run, and confirm the
   out-of-corpus refusal tests start failing.

## Developer note

- `evals/promptfooconfig.yaml` — test cases and judge configuration.
- `evals/README.md` — run instructions, tuning notes, known gaps.
- `apps/api-py/app/rag/retrieve.py` — `MIN_SIMILARITY` tuned from evidence.
