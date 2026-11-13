# 0029 — Knowledge bases: several corpora, each its own Qdrant collection

- **Status:** Accepted
- **Date:** 2026-11-13
- **Roadmap sub-stage:** E1.1 (Python extension; the first slice of multi-source RAG)

## Context

From 2026-11-13 the Java and Python editions grow **separately** (the owner's request: expand the AI-agent capabilities in each repo on its own, Java first, so the notes show what each stack teaches). Java has done multi-source RAG with routing (its ADRs 0017 to 0019: knowledge bases, three routing strategies, a measured comparison). This is the Python edition's first slice of the same concept: the application must hold **more than one corpus** (the CRM documents and, for example, another business's handbook) without them disturbing each other. Deciding *where to search* is the next slice (E1.2); this one only builds the corpora and their search.

The shared API contract and the MCP tool list are a contract with the Java edition and **do not change**. Everything here is new routes and settings, documented in [`python-extensions.md`](../python-extensions.md).

## Decision

1. **A knowledge base is an id, a label, a description and its own Qdrant collection.** The built-in `crm` knowledge base is the existing collection (`QDRANT_COLLECTION`), still ingested by `POST /documents/ingest` and untouched. Each extra one (setting `KNOWLEDGE_BASES`, a JSON list; default: the farm-supply handbook) has the collection `<QDRANT_COLLECTION>_<id, dashes as underscores>`, for example `document_chunks_agri_supply`, with the same two named vectors (`dense`, `bm25`).
2. **One collection per knowledge base, not one collection with a `knowledge_base` payload field.** CRM ingestion drops and recreates its collection, which would wipe a second corpus living inside it; the extra corpus must not appear in the `documents` table or the counts the contract checks; separate collections allow another embedding model later; and isolation becomes structural: a search of one knowledge base cannot return another's chunks because it never looks there. Same decision as the Java edition (its ADR 0017).
3. **The retriever is not copied: it is aimed.** `qdrant_store.collection_name()` returns a **`ContextVar`** override when one is set and the configured collection otherwise; `using_collection(name)` is a context manager that sets it for one block. `search_knowledge_base` runs the ordinary `retrieve_relevant_chunks` inside it, so hybrid search ([ADR 0019](0019-hybrid-search-and-reranker.md)), the similarity floor, the reranker and the embedding-model check all work for every knowledge base with no second implementation. A `ContextVar` is per asyncio task, so two concurrent requests for two knowledge bases never see each other's value (a test runs exactly that).
4. **The two retrieval caches are keyed by collection.** The point-count cache and the "was the index built with this embedding model" check were module-global, which would let the first collection's answer excuse the second. They are now dictionaries keyed by collection name; the reset helpers clear them. The model check reads the model recorded in **each collection's own metadata** (set when the collection is created, [ADR 0021](0021-embedding-models-and-reembedding.md)), and the message names the right fix: re-ingest this knowledge base (`POST /api/v1/knowledge-bases/<id>/ingest`), or for the CRM documents the documents route.
5. **Ingestion of an extra knowledge base is its own function** (`ingest_knowledge_base`): the same parser (`load_documents`, factored out of the CRM ingestion with no change in behaviour), chunker and embeddings, each chunk stored with its keyword vector and `knowledge_base` in the payload. It writes nothing to Postgres and never touches the CRM collection. A folder that does not exist is reported in the summary (HTTP 502), as the CRM ingestion reports a failed run. Searching a knowledge base that was never ingested returns an empty list, not an error.
6. **Routes (Python only):** `GET /api/v1/knowledge-bases`, `POST /api/v1/knowledge-bases/{id}/ingest`, `POST /api/v1/knowledge-bases/{id}/search` (`{"query": "...", "topK": 4}`; `topK` 1 to 20). The path id becomes a `KnowledgeBase` through a `Depends` function that answers 404, and the body is a pydantic model, so every bad request is FastAPI's own 422.
7. **Settings are validated at start-up:** an id is lower-case letters, digits and dashes; `crm` is reserved; ids are unique. A wrong `KNOWLEDGE_BASES` stops the API with a clear message rather than being ignored.
8. **The sample corpus is the Java edition's, byte for byte:** eight synthetic documents for a fictional farm-supply business (`sample-data/knowledge-bases/agri-supply/`), with the same id, label and description, so the two editions can later be compared on the same questions. The default folder is found next to the sample documents (and under `SAMPLE_DATA_DIR`'s parent in Docker).

## Python-specific concepts this slice teaches (for the notes)

These are things the Java slice did not need, or did differently:

- **`contextvars`.** Java builds one `Retriever` per knowledge base (constructor injection). Python code here uses module-level functions, so the target collection travels in an implicit, task-local variable instead of a parameter on every function. It is the asyncio-safe form of "thread-local", and the reason concurrent requests stay isolated.
- **FastAPI `Depends` with a path parameter.** A tiny function turns `{kb_id}` into the object or a 404, once, for every route that needs it; Java hand-wrote the lookup in each handler.
- **Pydantic request and settings models.** The search body, its limits and its 422 bodies come from one class (Java hand-rolled the FastAPI-shaped problems). `pydantic-settings` also parses a **list of nested models** straight from one JSON environment variable.
- **An in-process Qdrant for tests.** `AsyncQdrantClient(":memory:")` runs the real engine (named dense and sparse vectors, filters, collection metadata) in the test process, so the tests exercise real search with no container and no key; Java used Testcontainers. The suite uses a fake bag-of-words embedding, so it checks the flow and the isolation, not ranking quality.
- **Collection metadata as the source of truth.** The collection itself records its embedding model, so the model check is per collection and needs no Postgres table (Java reads the latest ingestion run).
- **Async fan-out is one line.** The next slice's "search everything" strategy is `asyncio.gather` over the knowledge bases (a test already runs two searches concurrently); Java used a loop on virtual threads.

## Alternatives considered

- **A `knowledge_base` field in one collection with a filter.** Fewer collections and one embedding model for all, but the wipe problem above, and every existing chunk would need re-ingesting to carry the field.
- **Threading a `collection` argument through every retrieval function.** Explicit, but a dozen signatures change (including the reranker, the agentic wrapper and the framework side) for one feature; a context variable is one place. The cost is that the dependency is implicit, which is why it is a context manager with a test for its scope.
- **A tenant table in Postgres.** More machinery than a learning extension needs; a validated settings list is enough until something must be edited at run time.

## Consequences

- Each extra knowledge base is one more pair of Qdrant collections (chunks and, inside the same collection, the keyword vector) and an empty search result until its first ingestion.
- All knowledge bases use the configured embedding model; the per-collection check will refuse a search against a collection built with another model and say how to fix it.
- `RETRIEVAL_IMPL=frameworks` (dense only, [ADR 0027](0027-retrieval-manual-or-langchain.md)) still works for a knowledge base because LangChain's store reads the same `collection_name()`; hybrid with it is refused at start-up as before.
- The existing contract suite passes unchanged (573 tests pass with this slice).

## Plan for the next slices (not started)

- **E1.2, routing strategies** on one Python-only route (`POST /chat/multi`), the same three as Java so the editions compare: a **router** (a model reads each description), **search all and merge** (`asyncio.gather`, reciprocal rank fusion, then the reranker), and an **agent** that picks a corpus through a `search_knowledge_base` tool. The Python angle: the router and the agent as a **LangGraph** graph (a conditional edge for routing, a tool node for the agent loop), with the same guard, audit and tracing as the chat routes.
- **E1.3, a replayable comparison** of the three on the same 24 labelled questions the Java edition used, with the same metrics, so the notes can set the two stacks side by side.
