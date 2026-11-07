# Stage 4 — Retrieval upgrade: find the right chunks more often

> **Level:** beginner friendly; read [Stage 3](03-langgraph-port.md) for how the 🟪agent uses 🟪retrieval. **Reading time:** about 15 minutes for what is written so far.
> **Status:** in progress. **4.1a (🟪hybrid search) and 4.1b (🟪reranker) are written; 4.2 (parsing) and 4.3 (🟪embeddings) are added when built.**
> **Roadmap:** [Stage 4](../roadmap.md#stage-4--retrieval-upgrade) · **Decisions:** [ADR 0019](../adr/0019-hybrid-search-and-reranker.md)

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](../ai-terms.md)

## In one minute

A 🟪RAG answer is only as good as the 🟪chunks it is given. Today's search finds chunks by **meaning** (an 🟪embedding). Meaning search is great at "what did Acme say about prices?" and weaker at "INV-4821", a name or an abbreviation, where the exact characters matter. 4.1a adds a second search by **exact words** and merges the two.

| Shop idea | Project idea | In the code |
| --- | --- | --- |
| A shop assistant who understands what you mean | **Dense search** (embeddings) | `_dense_points` in `app/rag/retrieve.py` |
| The index at the back of a book: look up the exact word | **Keyword search** (🟪BM25) | `app/rag/sparse.py`, 🟩Qdrant's `bm25` vector |
| Two assistants each hand you a ranked list; you merge by who placed where | **🟪Reciprocal rank fusion** | `rrf_fuse()` |
| A rule: "if it is nowhere near the question, do not cite it" | **The similarity floor** | `MIN_SIMILARITY`, kept in both modes |

## Concept 1 — Hybrid search (4.1a)

**Dense vs sparse.** A dense 🟪embedding is a list of 768 numbers that captures meaning. A 🟪sparse vector has one number per *word* and is mostly zeros: it records which words a 🟪chunk contains. Searching with it is keyword search.

**🟪BM25 in two halves.** BM25 scores a word by how often it appears in the chunk (with diminishing returns, corrected for chunk length) times how rare it is across all chunks. We compute the first half in `sparse.py` and let 🟩Qdrant compute the second: the `bm25` vector has the **IDF modifier**, which weights each word by its rarity. Rare words (`INV-4821`) then count far more than common ones (`the`).

**Merging.** 🟪Cosine scores and BM25 scores are on different scales, so they cannot simply be added. 🟪Reciprocal rank fusion ignores scores and uses positions: an item scores `1 / (60 + rank)` in each list that contains it, and the scores add up. Something both searches like wins; something only one finds still appears.

**The guard we kept.** Every chunk still needs a meaning-similarity of at least `MIN_SIMILARITY`. A chunk found only by keywords gets its similarity from its stored dense vector. So "What is the capital of France?" still 🟪retrieves nothing, even though it shares common words with many chunks. This is a deliberate trade-off recorded in the ADR.

**Switching it on.** `RETRIEVAL_MODE=dense` (default, Stage 3 behaviour) or `hybrid`. Re-ingest once after upgrading, because the collection now stores two vectors per chunk.

**Rule to remember.** *Meaning finds the neighbourhood; exact words find the street number. Use both, and merge by position, not by score.*

## Concept 2 — The reranker (4.1b)

**The problem.** Search is fast because it never reads the question and a 🟪chunk *together*: dense search compares two stored number-lists, keyword search counts words. So the top few results are good but not always in the best order, and the best chunk can sit at rank 3 behind two near-misses.

**The idea.** Take the best 20 or so candidates and hand them to a 🟪reranker: a second model that reads the question and each chunk together and scores how well they fit. It is slower and costs a call, so it only sees a short list. The final top 4 come from its order.

| Shop idea | Project idea | In the code |
| --- | --- | --- |
| The assistant fetches 20 possible folders quickly | **First-stage search** (dense or hybrid) | `retrieve_relevant_chunks` |
| A specialist reads each folder against your question and ranks them | **🟪Reranker** (a cross-encoder, hosted) | `app/rag/rerank.py` |
| If the specialist is away, you still get the assistant's order | **Graceful fallback** | `rerank_order` returns `None`, the search order stays |

**It is optional and cannot break 🟪retrieval.** `RERANK_PROVIDER=off` is the default. If it is on but there is no key, the call is slow, rate-limited, or the reply is nonsense, retrieval simply keeps the search order and logs one line (never the key or the provider's reply). That is the same rule production AI services follow for optional retrieval: *an enrichment must never take down the main path*.

**Two providers, one setting.** `voyage` (default model `rerank-2.5-lite`; the first 200 million tokens are free per account) or `cohere` (a trial key is limited to 10 requests a minute and 1,000 calls a month, so an evaluation run could use it up). Both are plain HTTP calls with a 5-second timeout, so there is no extra library.

**The guard is kept.** The similarity floor runs *before* the reranker, so a question with no relevant chunk still reaches the model with nothing to cite. The reranker only re-orders; it never adds a chunk the search did not find.

**Rule to remember.** *Search is wide and fast; the reranker is narrow and careful. Use the cheap one to get a shortlist and the careful one to order it, and never let the careful one be a single point of failure.*

---

## Code tour: what changed in 4.1a and 4.1b

| | Where | What |
| --- | --- | --- |
| 🟢 | `app/rag/sparse.py` | Tokenizer, stable word hash, 🟪BM25 term weights, query vector |
| 🟡 | `app/rag/qdrant_store.py` | Two named vectors per 🟪chunk (`dense`, `bm25` with the IDF modifier) |
| 🟡 | `app/rag/ingest.py` | Each chunk stores both vectors |
| 🟡 | `app/rag/retrieve.py` | `rrf_fuse`, `cosine`, `_keyword_points`; `retrieve_relevant_chunks` handles both modes |
| 🟡 | `app/config.py` | `retrieval_mode`, `retrieval_candidates`, `rrf_k` |
| 🟢 | `app/rag/rerank.py` | (4.1b) The hosted 🟪reranker call for Voyage and Cohere, parsing, and the "never raise" rule |
| 🟡 | `app/rag/retrieve.py` | (4.1b) a longer shortlist when a reranker is on, `_rerank`, the floor still first |
| 🟡 | `app/config.py`, `docker-compose.yml`, `.env.example` | (4.1b) `rerank_provider`, the two keys, the model and timeout; compose now passes `RETRIEVAL_MODE` and the rerank settings through |
| 🟢 | `tests/test_rerank.py` | (4.1b) 16 tests with a fake provider: requests, parsing, every failure |
| 🟢 | `tests/test_sparse.py`, `tests/test_hybrid_retrieval.py` | 16 tests, no key or database needed |
| 🟡 | `justfile` | `just eval-retrieval`, `just eval-hybrid` |
| 🟢 | [ADR 0019](../adr/0019-hybrid-search-and-reranker.md) | The decisions, including the reranker plan for 4.1b |

## Glossary

- **Dense vector / 🟪embedding**: a list of numbers that captures meaning.
- **🟪Sparse vector**: one number per word, mostly zeros; used for keyword search.
- **🟪BM25**: a keyword scoring formula: word frequency (with limits) times word rarity.
- **IDF**: inverse document frequency, the "how rare is this word" half of BM25.
- **🟪Reciprocal rank fusion (🟪RRF)**: merging ranked lists by position, `1 / (k + rank)`.
- **🟪Hybrid search**: dense plus keyword search, merged.
- **🟪Reranker / 🟪cross-encoder**: a model that reads the question and a 🟪chunk together and scores the fit; slower and more accurate than comparing stored vectors.
- **Recall@k, 🟪MRR**: how often the right document is in the top k, and how high the first right one ranks.

## Check your understanding

<details><summary>1. Why can a meaning search miss "INV-4821"?</summary>

An 🟪embedding blurs exact characters into a general meaning ("an invoice dispute"), so another invoice 🟪chunk can look just as close. A keyword search matches the exact token and, because that token is rare, scores it highly.
</details>

<details><summary>2. Why merge by rank and not by adding the scores?</summary>

🟪Cosine similarity and 🟪BM25 are on different scales, so adding them would let one dominate. Positions are comparable, so 🟪RRF needs no tuning.
</details>

<details><summary>3. Why do we keep the similarity floor in hybrid mode?</summary>

A keyword search always returns something that shares a word, even for an unrelated question. The floor, applied to meaning similarity, keeps "nothing relevant" an honest answer.
</details>

<details><summary>4. What happens to old data after upgrading?</summary>

It has only the dense vector, so 🟪hybrid search cannot use it. Ingest once again; it recreates the collection with both vectors.
</details>

<details><summary>5. How do we know hybrid search is no worse?</summary>

`just eval-hybrid` re-runs the 🟪retrieval suite with the mode switched on and compares recall and 🟪MRR with the saved baseline, within the agreed tolerance.
</details>

<details><summary>6. Why not rerank every chunk in the collection?</summary>

A 🟪cross-encoder reads the question with each chunk, so the cost grows with the number of chunks. It is only affordable on a short list that fast search has already narrowed down.
</details>

<details><summary>7. What happens if the reranker is down or has no key?</summary>

Nothing visible: retrieval keeps the search order and logs a warning. Reranking is an enrichment, so it must never be able to break the main path.
</details>

<details><summary>8. Does the reranker replace the similarity floor?</summary>

No. The floor runs first and decides what is relevant at all; the reranker only decides the order among what passed. An unrelated question still finds nothing to cite.
</details>

## Further reading

- 🟩Qdrant, hybrid queries and 🟪sparse vectors: <https://qdrant.tech/documentation/concepts/hybrid-queries/>
- Cormack, Clarke and Buettcher, "🟪Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods" (2009)
- Robertson and Zaragoza, "The Probabilistic Relevance Framework: 🟪BM25 and Beyond" (2009)
