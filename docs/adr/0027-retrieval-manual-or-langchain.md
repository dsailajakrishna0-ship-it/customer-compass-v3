# 0027 — Retrieval: our Qdrant query or LangChain's Qdrant vector store

- **Status:** Accepted: **manual wins**; the framework side ships as `RETRIEVAL_IMPL=frameworks` for dense search only
- **Date:** 2026-11-13
- **Roadmap sub-stage:** 5.5 (seam 2 of 3)

## Context

Dense retrieval is our code: embed the question, query Qdrant's `dense` vector, turn each hit into a `RetrievedChunk` ([ADR 0019](0019-hybrid-search-and-reranker.md)). `langchain-qdrant` (1.1.0, checked on PyPI on 2026-11-13) offers `QdrantVectorStore`, which does the same through LangChain's `Embeddings` and `Document` types. The roadmap asks whether it should replace our query.

## Decision

1. **`RETRIEVAL_IMPL=manual|frameworks`, default `manual`.** `retrieve_relevant_chunks` keeps its signature and result type. The LangChain side (`app/frameworks/retriever.py`) replaces only the dense query and the hit-to-chunk mapping; the index-model check, the company filter, the exact-versus-HNSW choice, the 0.45 floor's value, the reranker and the response stay ours, so the two sides differ in one thing.
2. **Dense only.** `RETRIEVAL_IMPL=frameworks` with `RETRIEVAL_MODE=hybrid` stops start-up with a clear message. Our keyword vector is our own code (BM25 weights, a CRC32 word hash) and the store cannot search it without LangChain's own sparse-embedding layer, which would replace our vector with a different one.
3. **Measured on the 42 retrieval questions** with the real `retrieve_relevant_chunks` against the same Qdrant collection, with the question vectors computed once so the timing is the search path (the embedding call is the same on both sides). The embedding model for this seam and the agent seam was **`BAAI/bge-small-en-v1.5` through FastEmbed** (local, free), because Google's free embedding quota for the day was used up while measuring; the chunker seam used `gemini-embedding-001`. Each comparison keeps its embedding model constant across the two sides, so the comparison holds; absolute recall numbers are not comparable with the Gemini baseline.

## Results

| | manual | frameworks |
| --- | --- | --- |
| questions with the same chunks, in the same order, as manual | 42 of 42 | 42 of 42 |
| recall@1 / recall@3 / recall@5 | 0.787 / 0.986 / 1.000 | 0.787 / 0.986 / 1.000 |
| MRR | 0.972 | 0.972 |
| median / p95 ms (search path, question vector given) | 6 / 7 | 5 / 6 |
| lines of code this side adds | 30 | 81 |

- **The answers are identical.** Same chunks, same order, same scores on all 42 questions. There is nothing to win on quality because there is nothing different.
- **Latency is the same.** One Qdrant query per search on both sides (measured by counting calls). The thread hop the store needs adds well under a millisecond.
- **It is more code.** 81 lines against 30: the framework needs an `Embeddings` adapter (our async Gemini call, called from the store's worker thread), a mapping from its `Document`s, and an extra payload copy at ingestion.

What the framework needed or did that our code does not (each one a thing to know before adopting it):

1. **Its own payload layout.** It reads a chunk's fields from a nested `metadata` key; our payload is flat. With the setting on, ingestion writes an extra nested copy (`_with_framework_metadata`). An index built without it returns chunks with no title.
2. **Cosine scores rescaled by its retriever interface.** `as_retriever(search_type="similarity_score_threshold")` turns a cosine `c` into `(1 + c) / 2`, so our 0.45 floor would silently become "keep nearly everything". The code calls the store's raw-score search with `score_threshold` instead.
3. **A hidden model call at construction.** Built with its defaults, the store embeds a dummy text and reads the collection's configuration. Inside the event loop that cannot run through our async adapter, so both checks are switched off (`validate_embeddings`, `validate_collection_config`).
4. **A sync-to-async bridge.** The store is synchronous; it runs in a worker thread and our async embedder is handed back to the loop (`run_coroutine_threadsafe`).
5. **No hybrid search for our index.** See decision 2.

## Decision on shipping

**Manual wins; keep it the default.** The framework matches our results exactly and adds nothing we need: no quality difference, no latency difference, 2.7 times the code, a payload change at ingestion, three gotchas that each would have been a bug (the rescaled floor, the construction-time embedding, the thread bridge), and no path to the hybrid search we already built. The side stays in the repository for the comparison and for the Java edition's notes.

**What would make us look again:** a LangChain retriever feature we do not have (a self-query retriever over metadata, a parent-document retriever) that a measured question set needs, or a vector store other than Qdrant, where the framework's common interface would save real work.

## Alternatives considered

- **LangChain's `EnsembleRetriever` for hybrid** (an in-memory BM25 retriever merged with the dense one): would need every chunk loaded into the process and a different keyword model from ours; it does not read our Qdrant keyword vector.
- **LlamaIndex's Qdrant integration:** the same shape of comparison; not run (two frameworks per seam would double the work for an answer that, here, is "no difference").

## Consequences

- `app/frameworks/retriever.py`, the ingestion helper and their tests run in CI through `just test-frameworks`.
- Re-ingest with `RETRIEVAL_IMPL=frameworks` before searching with it (the nested payload copy).
