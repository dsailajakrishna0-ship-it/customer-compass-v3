# 0039 — Comparison lab, RAG retrieval with LangChain

- **Status:** Accepted (E5.3; measured with a fake embedding model, a fake Gemini server, an in-memory Qdrant and a real Qdrant 1.20 server in a throw-away container; no live Gemini call)
- **Date:** 2026-11-26
- **Roadmap sub-stage:** E5.3 (the Python twin of the Java edition's J8.3; plan in [the E5 guide](../stages/E5-comparison-lab.md))

## Context

Retrieval embeds the question, asks the vector store for the closest chunks and keeps the ones similar enough to cite. The application keeps only chunks with a **cosine similarity of at least 0.60** (the value calibrated for `gemini-embedding-001`, ADR 0024). The Java lab found that a framework's score and threshold can be on another scale, so this comparison is mostly about that.

## Decision

1. **The same face as Java's retrieval backends:** `POST /api/v1/retrieve` with `{"query", "topK" (1 to 20, default 4), "minSimilarity" (0 to 1, default 0.60)}` and `GET /health`; the answer has `approach`, `collection`, `minSimilarity`, `considered`, `kept`, `hits` (`score`, `title`, `source`, `company`, `chunkIndex`, `text`), `embeddingRequests`, `embeddingModel`, `latencyMs`. A missing key, a missing collection or an unreachable service is a 503 that names the kind of failure, never a library's text or an address.
2. **withLangChain, port 19121,** searches the collection the E5.2 ingestion filled (`compare_withlangchain`) with `QdrantVectorStore.similarity_search_with_score(query, k=topK)`. One call embeds the question (🟦langchain-google-genai, task type `RETRIEVAL_QUERY`) and searches.
3. **The floor is applied by our own code on the raw score**, after asking for `topK` with no threshold, so `considered` (what the store returned) and `kept` (at or above the floor) are both known.
4. E5.3 also adds `chunk_index` (the chunk's number inside its document) to the ingestion's stored metadata, so a hit can say which chunk it is (the Java lab stores the same).

## What the LangChain classes did without our code (measured in `comparisons/tests/test_retrieval_langchain.py`)

| Behaviour | What LangChain does |
| --- | --- |
| Embedding the question and searching | One call, `similarity_search_with_score`; the question is embedded once |
| The score of that call | **Qdrant's cosine similarity**, as stored (a chunk stored at 0.6 comes back as `0.6000000238418579`, a float widened to a double, which is still at or above 0.60) |
| Metadata | Read back from the nested `metadata` payload the ingestion wrote (title, source, company, chunk index) |
| The Gemini call | Sends even one question through the **batch endpoint** (one request in the batch), with the task type, the dimensions and the key in the `x-goog-api-key` header |

## Where the scale differs (the finding to remember)

| Helper | What it returns | Effect on a floor of 0.60 |
| --- | --- | --- |
| `similarity_search_with_score` | the cosine | correct |
| `similarity_search_with_score(score_threshold=0.6)` | the cosine, filtered inside Qdrant at or above | correct, but **`considered` is hidden** (you cannot tell how many were returned) |
| `similarity_search_with_relevance_scores` | **`(cosine + 1) / 2`**: identical 1.0, orthogonal 0.5, opposite 0.0 | a floor of 0.60 would mean a cosine of 0.2 |
| `as_retriever(search_type="similarity_score_threshold", score_threshold=0.6)` | the same rescaled scores | **keeps a chunk of cosine 0.3** (measured), so the calibrated number silently means something else |

The approach therefore uses the first call and filters itself. This is the same lesson as LangChain4j's relevance score in the Java lab.

## What else it needed from us

| Point | Measured | In `withLangChain` |
| --- | --- | --- |
| Building a `QdrantVectorStore` | By default embeds a dummy text and reads the collection's configuration at construction | `validate_embeddings=False, validate_collection_config=False`: nothing but the search itself |
| A missing collection | The in-memory client raises `ValueError("Collection ... not found")`; **a real server raises a 404 `UnexpectedResponse`** (found only against the real server) | Both become: "The collection compare_withlangchain does not exist. Run the withLangChain ingestion first." |
| Wrong-length vectors | Not checked | Checked in our wrapper |
| `qdrant-client` | **`langchain-qdrant` 1.2.0 requires `qdrant-client` below 1.16**, while the application uses 1.19 or newer and the server is 1.20: the lab runs 1.15.1 against server 1.20, which prints a version-mismatch warning but worked for every call used here | Not suppressed; a project that already uses a newer client cannot add `langchain-qdrant` 1.2.0 to the same environment |

**Size:** the approach's file is 115 non-blank, non-comment lines (docstrings included).

## How this was run

`just comparisons-test` (98 tests, no key, no network, in CI) and, with a throw-away Qdrant (`docker run -p 26335:6333 qdrant/qdrant:v1.20.0`, `QDRANT_URL=http://localhost:26335`), 100 tests: the 29 chunks of the 16 sample Markdown files are ingested into the real server twice (no duplicates) and a chunk's own text as the question finds that chunk with a score of 1.0. The backend was also started once through `just` with a fake key and unreachable addresses: `GET /health` answers, a bad `topK` is a 422, and a search is a 503 `The embedding service failed (GoogleGenerativeAIError).` with the fake key in no log line.

**Not measured:** a real Gemini call (so real scores, and whether `RETRIEVAL_QUERY` against `RETRIEVAL_DOCUMENT` vectors scores differently from the application's), speed and cost, and search quality on real questions.
