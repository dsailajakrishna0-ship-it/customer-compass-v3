# Stage 4 — Retrieval upgrade: find the right chunks more often

> **Level:** beginner friendly; read [Stage 3](03-langgraph-port.md) for how the 🟪agent uses 🟪retrieval. **Reading time:** about 10 minutes for what is written so far.
> **Status:** in progress. **4.1a (🟪hybrid search) is written; 4.1b (🟪reranker), 4.2 (parsing) and 4.3 (🟪embeddings) are added when built.**
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

---

## Code tour: what changed in 4.1a

| | Where | What |
| --- | --- | --- |
| 🟢 | `app/rag/sparse.py` | Tokenizer, stable word hash, 🟪BM25 term weights, query vector |
| 🟡 | `app/rag/qdrant_store.py` | Two named vectors per 🟪chunk (`dense`, `bm25` with the IDF modifier) |
| 🟡 | `app/rag/ingest.py` | Each chunk stores both vectors |
| 🟡 | `app/rag/retrieve.py` | `rrf_fuse`, `cosine`, `_keyword_points`; `retrieve_relevant_chunks` handles both modes |
| 🟡 | `app/config.py` | `retrieval_mode`, `retrieval_candidates`, `rrf_k` |
| 🟢 | `tests/test_sparse.py`, `tests/test_hybrid_retrieval.py` | 16 tests, no key or database needed |
| 🟡 | `justfile` | `just eval-retrieval`, `just eval-hybrid` |
| 🟢 | [ADR 0019](../adr/0019-hybrid-search-and-reranker.md) | The decisions, including the 🟪reranker plan for 4.1b |

## Glossary

- **Dense vector / 🟪embedding**: a list of numbers that captures meaning.
- **🟪Sparse vector**: one number per word, mostly zeros; used for keyword search.
- **🟪BM25**: a keyword scoring formula: word frequency (with limits) times word rarity.
- **IDF**: inverse document frequency, the "how rare is this word" half of BM25.
- **🟪Reciprocal rank fusion (🟪RRF)**: merging ranked lists by position, `1 / (k + rank)`.
- **🟪Hybrid search**: dense plus keyword search, merged.
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

## Further reading

- 🟩Qdrant, hybrid queries and 🟪sparse vectors: <https://qdrant.tech/documentation/concepts/hybrid-queries/>
- Cormack, Clarke and Buettcher, "🟪Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods" (2009)
- Robertson and Zaragoza, "The Probabilistic Relevance Framework: 🟪BM25 and Beyond" (2009)
