# ADR 0031: the CRM similarity floor is 0.60 (E1.4)

Status: accepted, 2026-11-14. Changes the Stage 6 value of 0.45 in both editions (the Java edition makes the same change in its own PR).

## Context

A chunk is cited only if its cosine similarity to the question reaches `MIN_SIMILARITY`. It was 0.45, tuned in Stage 6 on a few sampled questions. The Java edition's E1.4 slice (its ADR 0023) measured it on 24 labelled questions against `gemini-embedding-001`:

- The best chunk of each relevant CRM question scored at least 0.605; the best chunk of each unrelated question at most 0.597.
- At 0.45, 10 of 12 unrelated questions still found chunks to cite.
- At 0.60, all 12 relevant questions keep their best chunk and none of the 12 unrelated ones does. Twelve extra held-out questions agreed (4 of 4 relevant kept, 0 of 8 unrelated let through).

## Decision

`MIN_SIMILARITY = 0.60` in `apps/api-py/app/rag/retrieve.py`. It applies to dense, hybrid and `RETRIEVAL_IMPL=frameworks` retrieval alike.

## Costs and limits (read before trusting it)

- **The margin is 0.008.** The samples are small (12 questions per corpus), so another run of questions may land on either side.
- **Weaker supporting chunks are lost.** Counting the chunks of the right documents, 0.60 keeps 22 of 24 in the top four (about 8% lost) and 23 of 28 in the top ten. Every question still keeps its best chunk, and 2 of 12 lose a supporting one.
- **Stage 6 reported "other matches" scoring 0.50 to 0.69**, so some of those now fall below the floor. The golden retrieval evaluation (`evals/baseline/v2.json`) was measured at 0.45; recall figures can move. The baseline has to be re-measured with a live stack before it is replaced (`just eval-baseline`), so it is not changed in this PR.
- **Model-specific.** A different embedding model needs a new calibration; the floor does not carry over.
- **Not a cure for plausible-but-uncovered questions** such as a refund policy; the model's "not in the sources" answer remains the safety net.

## Alternatives considered

- **0.55:** loses almost no chunks (1 of 28) but still lets 3 of 12 unrelated questions through.
- **Keep 0.45:** no recall risk, but unrelated questions keep citing sources.
