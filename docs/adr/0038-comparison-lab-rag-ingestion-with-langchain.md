# 0038 — Comparison lab, RAG ingestion with LangChain

- **Status:** Accepted (E5.2; measured with a fake embedding model, a fake Gemini server and an in-memory Qdrant, no live run)
- **Date:** 2026-11-26
- **Roadmap sub-stage:** E5.2 (the Python twin of the Java edition's J8.2 `withLangchain4j`; plan in [the E5 guide](../stages/E5-comparison-lab.md))

## Context

Ingestion is Read, Chunk, Embed, Store. The Java lab built it by hand, with Spring AI and with LangChain4j behind one HTTP face. The Python lab has only the 🟦LangChain side here (LangGraph does not own these jobs; the application is the hand-written side).

## Decision

1. **The same face as Java's ingestion backends:** `POST /api/v1/ingest` (optional `{"limit": n}`, 1 to 1,000) and `GET /health`; the source folder and the collection are fixed by the backend. The answer has `approach`, `status`, `collection`, `documents`, `chunks`, `embeddingRequests`, `embeddingModel`, `dimensions`, `latencyMs`. A missing key or an unreachable service is a 503 that names the kind of failure, never a library's text or an address.
2. **withLangChain, port 19111, collection `compare_withlangchain`**, Markdown files of `sample-data/documents` in file name order, **600 characters with 100 overlap**, `gemini-embedding-001` at 768 dimensions with the task type `RETRIEVAL_DOCUMENT`, 100 texts per embedding request:
   - **Read:** `TextLoader` (🟦langchain-community), one file at a time.
   - **Chunk:** `RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=100, add_start_index=True)`.
   - **Embed:** `GoogleGenerativeAIEmbeddings` (🟦langchain-google-genai).
   - **Store:** `QdrantVectorStore` (🟦langchain-qdrant) over the Qdrant REST client, port 26333 by default.
3. **What we add around the classes:** the front matter (title and company), the order **embed first, then replace the collection**, a check of every vector's length, the request count, and the safe error messages.

## What the LangChain classes did without our code (measured in `comparisons/tests/test_ingestion_langchain.py`)

| Behaviour | What LangChain does |
| --- | --- |
| Reading | `TextLoader` returns one document per file with only `source` in its metadata |
| Cutting | A splitter that works on plain text and, with `add_start_index=True`, records each chunk's character offset (LangChain4j's splitter has none) |
| The Gemini call | Batches **100 texts per request** by itself (250 texts: 3 requests of 100, 100 and 50), puts the **key in the `x-goog-api-key` header** (not the URL), and sends the task type and the output dimensions |
| Storing | Writes each chunk as a point with `page_content` and a nested `metadata` payload and a random id |

## What it did not give, or did in a way you would not guess

| Point | Measured | In `withLangChain` |
| --- | --- | --- |
| Front matter | The loader **keeps it in the text** (`---`, `title:` ...); there is no title or company | Parsed with `python-frontmatter` and cut off before splitting |
| `QdrantVectorStore.from_documents` | Embeds the **first text once to learn the dimension, then embeds everything**: that text is sent twice | Not used |
| Building a `QdrantVectorStore` | By default embeds a dummy text and reads the collection's configuration at construction (a hidden model call) | `validate_embeddings=False, validate_collection_config=False`: no call |
| Replacing the collection | `force_recreate=True` recreates the collection **before** embedding, so a failed embedding run would have deleted the old data | The vectors are computed first; only then is the collection dropped and created; the store gets the ready vectors through a small `Embeddings` class, so it does not embed again (a failed embedding run leaves the old data, tested) |
| Wrong-length vectors | Not checked by the Gemini class | Checked in our wrapper |
| Point ids | Random ids, so the ids are not the application's ids | Not changed (the Java lab's retrieval comparison is the place where ids matter) |

**A finding about the packages:** `langchain-community`, where `TextLoader` lives, prints a **deprecation warning at import** ("is being sunset and is no longer actively maintained"). The same job is a few lines of plain Python (`Path.read_text`), so a project that does not already use the package should not take it for this. It is used here because the point of the lab is to show the framework's own loader. Installing it also pulled in SQLAlchemy and NumPy.

**Size:** the approach's file is 154 non-blank, non-comment lines (docstrings included): the pipeline is short, and most of the lines are the parts the library did not give (front matter, the replace order, the length check, the request count, the error messages).

## How this was run

`just comparisons-test` (68 tests, no key, no network, in CI). On the 16 Markdown files of `sample-data/documents` the fake-embedding run gives **29 chunks** in 1 embedding request. The backend was also started once through `just` with a fake key and unreachable addresses: `GET /health` answers, a bad `limit` is a 422, and a run is a 503 `The embedding service failed (GoogleGenerativeAIError).` with the fake key in no log line.

**Not measured:** a run against the real Gemini API and a real Qdrant (needs `GOOGLE_API_KEY` and `just qdrant`, and your "go"), cost and speed, and whether the chunks differ in quality from the application's own.
