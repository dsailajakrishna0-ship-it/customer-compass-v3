# 0019 — Hybrid search with our own BM25 vectors, and a hosted free-tier reranker

- **Status:** Accepted
- **Date:** 2026-11-06
- **Roadmap sub-stage:** 4.1 (split into 4.1a and 4.1b)

## Context

Retrieval today is dense only: the question is embedded and Qdrant returns the closest chunks by meaning. That blurs exact terms (a deal name, an invoice id, an abbreviation). 4.1 adds keyword matching (hybrid search) and a reranker that re-orders the candidates. The exit criterion is that recall@k and MRR are at least the baseline. The baseline is already near its ceiling (MRR 1.00, recall@3 0.99), so the realistic goal of 4.1a is "no regression, and the exact-word cases work"; harder questions are added when the baseline is next re-taken.

Two constraints from earlier decisions: V3 is cloud-only ([ADR 0010](0010-cloud-only-v3.md)), and everything must run on free tiers.

## Decision

1. **Split in two PRs.** 4.1a is hybrid search; 4.1b is the reranker. Each is measured on its own.
2. **Keyword vectors are built in our code** (`app/rag/sparse.py`), not by a library or a model: words are hashed to stable indices, and each chunk's weights are BM25's term-frequency part. Qdrant's **IDF modifier** on the `bm25` sparse vector supplies the rarity part, so the two together are BM25. No new dependency, no model, and the maths is small enough to read.
3. **Each chunk point has two named vectors**, `dense` and `bm25`. The collection is recreated at ingestion (as it already was), so existing data needs one re-ingest.
4. **Two searches, merged in Python by reciprocal rank fusion** (`rrf_fuse`, k = 60), not with Qdrant's built-in fusion query. Reason: Qdrant's fused score is rank-based, but our citation filter and the UI use the meaning similarity (cosine). Merging ourselves lets every chunk keep a real cosine, computed from its stored dense vector when only the keyword search found it. The same `MIN_SIMILARITY` floor therefore applies in both modes, so unrelated questions still retrieve nothing.
5. **A setting chooses the mode:** `RETRIEVAL_MODE=dense|hybrid`, default `dense`. The default flips to `hybrid` only after `just eval-hybrid` shows no regression with a real key. The API response shape does not change, so the contract and the Java edition are unaffected.
6. **The reranker (4.1b) is a hosted free-tier API, optional and time-limited.** Provider choice, checked on the providers' own pages on 2026-11-06: **Voyage AI** `rerank-2.5` / `rerank-2.5-lite` (the first 200 million tokens are free per account, no monthly call cap stated) is the default; **Cohere** Rerank is the alternative (Trial key: 10 requests per minute, 1,000 API calls per month across all endpoints, not for production use). A `RERANK_PROVIDER` setting (`off`, `voyage`, `cohere`; default `off`) selects it, calls go through plain `httpx` with a short timeout, and any failure returns the candidates in their original order, so retrieval never breaks because a reranker is slow or down (the same "optional enrichment" rule the production email services in the discussion use).

## Alternatives considered

- **Qdrant's server-side fusion (`Prefetch` plus `FusionQuery`).** Less code, but the fused score replaces the cosine our floor needs; we would lose the similarity guard or compute it separately anyway.
- **FastEmbed's BM25 or SPLADE sparse models.** Better keyword handling (stemming, learned weights) but a new dependency and, for SPLADE, a local neural model. Stage 4.3 already compares FastEmbed for embeddings; sparse models can join that comparison.
- **A local cross-encoder reranker.** No key needed, but it brings a model download and CPU inference into the API image, against ADR 0010.
- **Cohere as the default reranker.** Its Trial key is limited to 10 requests per minute and 1,000 calls a month, which an evaluation run would use up.
- **Replace dense with keyword search.** Loses synonyms and paraphrase, the reason for embeddings.

## Consequences

- One re-ingest is needed after upgrading (the collection schema changed); `just up` then the **Ingest documents** button, or `POST /documents/ingest`.
- A chunk found only by keywords is still dropped if its meaning is far from the question. This is deliberate (it keeps the "unanswerable questions find nothing" guard) and is something to measure: if exact-term rescues matter more, the floor can be made mode-specific.
- Our tokenizer is simple (lower-case words and numbers, no stemming, no stop-word list). IDF already down-weights common words; stemming is a later option.
- Hash collisions between two words are possible in a 32-bit index space; with this corpus size they only blur a score.
- 4.1b adds a key (`VOYAGE_API_KEY` or `COHERE_API_KEY`), a new outbound call, and a latency cost per question; the setting defaults to off.
