# Extension E1 — Multi-source RAG: more than one knowledge base

> **Level:** beginner friendly; read [Stage 4](04-retrieval-upgrade.md) first (it explains how one collection is searched). **Reading time:** about 15 minutes.
> **Status:** E1.1 written (🟪knowledge bases). E1.2 (routing strategies) and E1.3 (a comparison) are planned.
> **Roadmap:** [Extensions after parity](../roadmap.md#extensions-after-parity-from-2026-11-13) · **Decision:** [ADR 0029](../adr/0029-knowledge-bases.md) · **List of Python-only additions:** [python-extensions](../python-extensions.md)

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](../ai-terms.md)

## In one minute

Until now the application searched **one** pile of documents: the CRM's emails, notes, tickets and contracts. A real assistant often has to look in more than one place: the CRM, and also a product handbook, a policy library, another business's manual. That is **🟪multi-source RAG**. It has two halves: holding several corpora so they do not disturb each other (this guide, E1.1), and deciding **where to look** for a given question (E1.2).

**Not the same as multimodal 🟪RAG.** Multimodal RAG is *one* index that holds many kinds of content (text, images, video). Multi-source RAG is *several* indexes. Each of them can be multimodal.

| Library idea | Project idea | In the code |
| --- | --- | --- |
| A library with several separate sections | A **🟪knowledge base**: an id, a description and its own 🟩Qdrant collection | `app/rag/knowledge_bases.py` |
| The "General" section, always there | The built-in `crm` knowledge base: the existing collection, unchanged | `QDRANT_COLLECTION` |
| A new section that arrives on its own trolley | An extra knowledge base, ingested by its own function and never touching the others | `ingest_knowledge_base()` |
| A librarian who only searches the shelf you point at | Searching one knowledge base: the ordinary 🟪retrieval, aimed at its collection | `search_knowledge_base()` |
| A sign on each section saying what is inside | The **description**: what a router (E1.2) reads to choose a section | `KNOWLEDGE_BASES` setting |

```
 POST /documents/ingest ───────────▶  crm            (collection document_chunks)
 POST /knowledge-bases/agri-supply/ingest ▶  agri-supply   (collection document_chunks_agri_supply)

 POST /knowledge-bases/crm/search ─────────▶ looks only in document_chunks
 POST /knowledge-bases/agri-supply/search ─▶ looks only in document_chunks_agri_supply
```

## Concept 1 — One collection per corpus

Two ways to hold two corpora: put everything in one collection and tag each 🟪chunk with its corpus (then *filter* at search time), or give each corpus its own collection. We use separate collections, for three reasons that all come from the corpus's **lifecycle**:

- **Re-ingesting the CRM documents drops and recreates its collection.** If the second corpus lived inside it, it would be wiped every time.
- **The extra corpus must not leak into the CRM's own bookkeeping**: the `documents` table, the ingestion runs and the counts the API contract checks (19 documents, 33 chunks).
- **Isolation becomes structural.** A search of one 🟪knowledge base cannot return another's chunks because it never looks there; there is no filter to forget.

A second benefit: each collection records the 🟪embedding model that built it, so a corpus built with an older model is noticed on its own and the message says which route to call to fix it.

## Concept 2 — Aim the retriever, do not copy it

🟪Retrieval ([Stage 4](04-retrieval-upgrade.md)) is a set of module functions that find "the collection" through one helper, `collection_name()`. For a 🟪knowledge base we do not write a second retriever; we **point the first one somewhere else for a moment**:

```python
with using_collection("document_chunks_agri_supply"):
    chunks = await retrieve_relevant_chunks("How long must workers stay out after spraying?")
```

Inside the block, `collection_name()` returns the knowledge base's collection, so 🟪hybrid search, the similarity floor, the optional 🟪reranker and the embedding-model check all apply, with no change to them. The target travels in a **`ContextVar`**, Python's task-local variable: each asyncio task sees only its own value, so two requests for two knowledge bases running at the same moment cannot cross (a test runs exactly that). The two small caches in retrieval (the point count, the model check) are keyed by collection name for the same reason.

## Concept 3 — The description is data for the router

An extra 🟪knowledge base is configured with a **description** of what is inside (`KNOWLEDGE_BASES`, a JSON list). Nothing reads it yet in E1.1 except the list route; in E1.2 a router (or the model itself) will read the descriptions to decide which corpus can answer a question. That makes the description an *interface*: vague descriptions will give bad routing. The sample corpus (eight synthetic farm-supply documents) deliberately shares some vocabulary with the CRM documents (renewal, pricing, support, delivery), so a router cannot decide on vocabulary alone.

## Concept 4 — Idioms worth noticing (Python)

- **`Depends` with a path parameter** turns `{kb_id}` into the object or a 404 once, for every route.
- **A pydantic model** is the search body, its limits and its 422 messages in one class; `pydantic-settings` parses the whole `KNOWLEDGE_BASES` list of nested models from one JSON variable.
- **An in-process 🟩Qdrant** (`:memory:`) runs the real engine in the test process, so the tests exercise real 🟪vector search with no container and no key.

## How to try it

```bash
just up && just seed                                          # the stack (API on localhost:8001) and the CRM documents (needs the embedding key)
just kb-ingest agri-supply                                    # the second corpus: 8 documents
just kb-list                                                  # two rows: crm 33 chunks, agri-supply about 13
just kb-search agri-supply "How long must workers stay out of a block after spraying?"
just kb-search crm "How long must workers stay out of a block after spraying?"
```

Notice: the first search returns only `knowledge-bases/agri-supply/...` sources; the second returns only CRM documents (probably weak matches); ingesting the CRM documents again leaves the farm-supply count unchanged.

## What comes next

**E1.2** decides where to search, three ways, on one Python-only route: a **router** (a model reads the descriptions), **search all and merge** (`asyncio.gather`, 🟪reciprocal rank fusion, then the 🟪reranker) and an **🟪agent** that picks a corpus through a tool, with the router and the agent as a 🟦LangGraph graph. **E1.3** measures the three on the same 24 labelled questions the Java edition used.
