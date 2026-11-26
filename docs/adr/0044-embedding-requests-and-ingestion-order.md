# 0044 — Embedding requests (key in a header, batches of 100) and ingestion that embeds before it replaces

- **Status:** Accepted (implemented in the same change; measured with a fake HTTP transport and fakes, **not against the live Google service**)
- **Date:** 2026-11-28
- **Origin:** three weaknesses of the application's own ingestion that the comparison lab ([ADR 0038](0038-comparison-lab-rag-ingestion-with-langchain.md) and [0039](0039-comparison-lab-rag-retrieval-with-langchain.md)) made visible by contrast.

## Context

`app/rag/embeddings.py` called Google's `embedContent` endpoint **once per text**, with the API key as a **query parameter** (`?key=...`), and `ingest_documents` / `ingest_knowledge_base` **emptied the index (and the Postgres rows) before embedding**, document by document. So:

1. **The key was in the URL.** The API logger already stays quiet for it (`app/logs.py`), but a URL with a key can still reach a proxy, an access log or an error report.
2. **A text took one request.** The 19 sample documents give 29 chunks, so 29 requests; a larger corpus is slow and burns the per-request quota.
3. **A failed embedding call destroyed the old index.** The collection and `documents` table were cleared first, so a failed or refused request half-way left a partial index (the first documents only) with the previous one gone.

## Decision

1. **The key goes in the `x-goog-api-key` header**, set once on the HTTP client. The URL has no query.
2. **Texts go through `:batchEmbedContents`, up to 100 per request** (the endpoint's limit), in input order. **Each text is sent exactly as before** (same model, same content, same `outputDimensionality` of 768), so the vectors are the ones the existing indexes hold; there is **no re-embedding and no change of the stored model id**. The reply must hold exactly one vector per text, otherwise the call fails with a plain message.
3. **Ingestion is two phases.** First, read-only: cut every document into chunks and embed **all chunks of all documents in one call** (batched as above). Only then replace: truncate the rows, recreate the collection, insert and upsert. An embedding failure (no key, a refusal, an unusable reply) therefore leaves the **previous index exactly as it was**, and the run is recorded as failed as before. The same change is made for the knowledge-base ingestion (`POST /api/v1/knowledge-bases/{id}/ingest`).
4. **Not changed:** the task type (the application never sent `RETRIEVAL_DOCUMENT` or `RETRIEVAL_QUERY`; adding it would change the vectors and force a re-embedding, so it is left for a measured decision of its own), the chunker, the payload, the error messages of the routes, the local FastEmbed provider.

## Consequences

- **Memory:** all vectors of a run are held until the replace: 768 floats per chunk, about 6 KB as Python floats, so 30,000 chunks would be about 180 MB. Fine for this corpus; a much larger one would need a staging collection that is swapped in (not built).
- **Quota:** a batch of 100 is one HTTP request, but whether Google's free-tier counter counts one request or 100 embeddings is **not verified** here (no live run); if it counts embeddings, the saving is in time and connections, not in quota.
- **Equivalence of vectors** between the old single-text call and the batch call is expected (the same item body) and **not measured against the live service**; the first run with a key will show it (a re-ingestion followed by the golden-set check `just eval-baseline`).
- **Rollback** is a revert of this change; nothing is stored differently.

## How this was checked (key-less)

`apps/api-py/tests/test_embedding_requests.py` (8 tests): the key is in the header and not in the URL; 250 texts become requests of 100, 100 and 50 with the vectors back in input order; the body of each text is the old one; no text means no request; a refusal is a plain message with neither the key nor Google's reply; a reply with a missing or malformed vector is refused; no key means no request. `tests/test_ingest_order.py` (4 tests): the CRM ingestion embeds all chunks in **one** call **before** the truncate and the recreate; a failed embedding call leaves both untouched and records `failed`; the vectors reach the right chunks in order; the knowledge-base ingestion embeds before it recreates and a failure leaves its collection alone. The whole API suite (733 tests) and the 26 contract tests pass unchanged.
