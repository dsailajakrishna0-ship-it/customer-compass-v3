# Stage 3 — Basic RAG

**Part:** I — Foundations
**Status:** Completed

> **v2 stack note:** this record describes the original v1 implementation
> (Express API on port 3001, Ollama `mxbai-embed-large` embeddings, pgvector).
> In v2 the API is FastAPI (`apps/api-py`, port 8001, `/api/v1/...`,
> files `app/rag/*.py`), embeddings are Google `gemini-embedding-001`
> (768-dim; an embedding model that turns text into vectors, not a chat model)
> and vectors live in Qdrant (a vector database). See
> [../architecture.md](../architecture.md) and [../tech-stack.md](../tech-stack.md).
> Paths, ports, models and curl examples below are kept as originally recorded.

## Goal

Build a transparent Retrieval-Augmented Generation pipeline using synthetic CRM
documents. The output must be grounded and cite its source chunks.

## Concepts: embeddings, semantic search, cosine similarity

This stage leans on a few terms that show up throughout the rest of the docs
(`embedding`, `semantic search`, `cosine similarity`, `vector`) without
re-explaining them every time. Here's what they mean, in plain language.

**Embedding** — a numerical fingerprint of meaning. An embedding model reads a
piece of text and outputs a fixed-length list of numbers (a *vector*) — this
app uses Ollama's `mxbai-embed-large`, which outputs 1024 numbers per chunk.
Texts with similar *meaning* produce vectors that point in similar
directions, even if they don't share any of the same words.

```text
"Can we set alerts per customer?"        -> [0.12, -0.08, 0.44, ... ]  (1024 numbers)
"Does the plan support per-client alarms?" -> [0.14, -0.07, 0.41, ... ]  (close by)
"What's the invoice due date?"             -> [-0.51, 0.33, 0.02, ... ]  (far away)
```

**Semantic search** — searching by *meaning* instead of by matching exact
keywords. A traditional keyword search for "alerts per customer" would miss a
document that says "per-client alarms" — no shared words. Semantic search
finds it anyway, because the two phrases embed to nearby vectors. This is
what makes RAG retrieval work here: the question and every document chunk are
embedded into the same vector space, and "relevant" is redefined as "nearby
in that space."

**Cosine similarity** — the specific way "nearby" is measured. Instead of
measuring the straight-line distance between two vectors, cosine similarity
measures the *angle* between them — it asks "do these two vectors point in
the same direction?", not "are these two points close together?". The result
is always between -1 (opposite meaning) and 1 (identical meaning); this app
treats anything below 0.3 as not relevant enough to cite (see
`MIN_SIMILARITY` in `apps/api/src/rag/retrieve.ts`).

```text
          ▲
          │      • question embedding
          │     ╱
          │    ╱  θ (small angle → high similarity)
          │   ╱
          │  • relevant chunk embedding
          │
          │              • unrelated chunk embedding
          │             (large angle → low similarity)
          └──────────────────────────────────────────▶
```

Postgres computes this directly on stored vectors via `pgvector`'s `<=>`
operator (`1 - (dc.embedding <=> $1) AS similarity` in `retrieve.ts`) — no
separate vector database is needed; the embeddings live in a normal
`document_chunks` table column.

## Vector indexing methods (concept + demo)

### Exact vs approximate nearest neighbour (k-NN vs ANN)

Retrieval asks: which stored vectors are nearest to the query? Computing the
distance to **every** vector gives the exact answer (**k-NN**, "k nearest
neighbours") but costs time proportional to the number of vectors times the
dimensions (768 here). In high dimensions, tree-style exact indexes (like
k-d trees) stop helping, so exact search does not scale past modest sizes.

**ANN (approximate nearest neighbour)** search accepts "almost always the
true top-k" in exchange for a large speed-up. The quality measure is
**recall@k**: the share of the true top-k that the approximate search returns.
Main ANN families:

- **Graph-based:** HNSW (what Qdrant uses).
- **Cluster-based:** IVF (inverted file).
- **Hashing:** LSH (locality-sensitive hashing), which maps similar vectors to the same bucket.
- **Compression-based:** product quantization (PQ), which stores compact codes and is often combined with IVF.

Libraries and engines implement these, for example FAISS, ScaNN and Annoy,
and vector databases such as Qdrant and pgvector wrap them. RAG usually
tolerates a small recall loss, because the LLM only needs the relevant chunks
to appear in the top few, not a perfect ranking. Only HNSW is measured in the
demo below; the others are described only.

### Index methods compared

Finding the nearest vectors by comparing against every stored vector is
**exact (flat) search**: always correct, but cost grows with the number of
chunks. A vector database builds an **index** to avoid that, trading a little
accuracy (*recall*: how many of the true top-k it finds) for speed.

| Method | Idea | Trade-off |
| --- | --- | --- |
| **Flat** | Compare against every vector | Perfect recall, slowest at scale |
| **IVF** (inverted file; pgvector `ivfflat`) | Cluster vectors, search only the nearest clusters | Needs training data; recall depends on how many clusters are probed |
| **HNSW** (hierarchical navigable small world; Qdrant's default, pgvector `hnsw`) | Layered graph of neighbours; walk it from coarse to fine | Fast and high recall; uses more memory and build time |

HNSW knobs: `m` (links per node) and `ef_construct` (build effort) are set
when the index is built; `hnsw_ef` (search effort) is set per query. Higher =
better recall, slower. **Quantization** (storing smaller numbers per
dimension) cuts memory further at some accuracy cost. A **payload index**
(e.g. on `company_id`) makes filtered search fast, which is what our
company-scoped queries use.

**Our setup:** the Qdrant collection in `app/rag/qdrant_store.py` sets only
the size (768) and cosine distance, so Qdrant applies its **default HNSW
settings** (`m=16`, `ef_construct=100`), with no quantization and no payload
index. We write no index code or tuning ourselves; the only index
configuration in this repo is in `evals/vector_index_demo.py`.

Caveat: Qdrant only builds the HNSW graph once a segment holds enough vector
data (`indexing_threshold`, 10,000 KB by default in the version we checked,
roughly 3,000 vectors of 768 floats), and uses a plain scan for filtered
queries that match few points (`full_scan_threshold`). With 16 documents our
searches are therefore effectively **exact**, not approximate. The index only
starts to matter as the corpus grows. IVF is not used anywhere in this repo
(the old pgvector setup had no index either).

### How the index works and how it decides

**HNSW** is a layered graph. Each vector is a node linked to its near
neighbours; upper layers are sparse "highways" and the bottom layer holds every
point.

- *Build (`m`, `ef_construct`).* Each new vector enters at a random layer, finds
  its nearest neighbours with a search of width `ef_construct`, and links to up
  to `m` of them. Bigger values give a better graph but slower, larger builds.
- *Search (`hnsw_ef`).* Start at the top layer, greedily hop to whichever
  neighbour is closer to the query, drop a layer, and repeat. On the bottom
  layer keep the `ef` best candidates and return the top `k`. The search stops
  when no candidate improves, which is why it can miss a true neighbour
  (recall below 1.00) and why a larger `ef` helps.
- *Who decides.* Qdrant, not our code. It decides when to build (the thresholds
  above), builds in the background, and picks between graph search and a plain
  scan per query. We only choose settings, if we choose any.

**IVF (inverted file)** works differently, and Qdrant does not offer it (it is
found in FAISS and pgvector's `ivfflat`).

- *Build.* Run k-means over the vectors to make `nlist` cluster centres, then
  assign every vector to its nearest centre.
- *Search.* Compare the query with the centres, then scan only the `nprobe`
  nearest clusters. More probes means higher recall and more work.
- *Trade-off.* It needs the data present to train the clusters, and when new
  data drifts the clusters go stale and need a rebuild. HNSW inserts one point at
  a time without retraining but uses more memory.

**How to choose:** for small data, use no index (exact scan). For general
semantic search with updates, use HNSW. When memory is the limit or data is huge
and mostly static, consider IVF, often with product quantization. Tune by
measuring recall@k and latency on your own questions.

**Demo:** `evals/vector_index_demo.py` (needs a real Qdrant server; usage is
in the file's docstring). Run it from the branch/checkout that contains the
file:

```bash
docker run -d --rm --name qdrant-demo -p 6335:6333 qdrant/qdrant
cd apps/api-py && uv run python ../../evals/vector_index_demo.py http://localhost:6335
docker stop qdrant-demo
```

It creates 20,000 synthetic, clustered 768-dim vectors (the size of our
Gemini embeddings), then compares the methods. One local run:

| Search | recall@10 | ms/query |
| --- | --- | --- |
| Exact (flat) | 1.00 | 7.7 |
| HNSW `ef=8` | 0.96 | 3.7 |
| HNSW `ef=32` | 1.00 | 3.1 |
| HNSW `ef=128` | 1.00 | 4.2 |
| Filtered, no payload index | 1.00 | 7.0 |
| Filtered, with payload index | 1.00 | 4.0 |

Read these as the shape of the trade-off, not benchmarks: the data is
synthetic and small, timings are noisy, and the gap grows with collection
size. IVF was **not** measured here (Qdrant doesn't offer it); it is only
described, as are LSH and PQ.

### Reading the demo output

A second run on another machine printed:

```text
20000 vectors, 768 dims, cosine; indexed_vectors_count=20000

Unfiltered search (recall@10 against exact search)
  exact (flat)   recall 1.00     6.48 ms/query
  HNSW ef=8     recall 0.95     2.50 ms/query
  HNSW ef=32    recall 1.00     2.75 ms/query
  HNSW ef=128   recall 1.00     3.55 ms/query

Filtered search, company_id = 3 (ef=32)
  no payload index   recall 1.00     5.39 ms/query
  with payload index recall 1.00     3.48 ms/query
```

Line by line:

- **Header.** 20,000 random vectors of 768 numbers each, compared by cosine.
  `indexed_vectors_count=20000` means Qdrant finished building the HNSW index
  over all of them; the script waits for this so timings are not skewed by a
  half-built index.
- **Unfiltered search.** 100 queries, each asking for the 10 nearest vectors.
  *Recall* is how many of the true top 10 the method returned.
  - *Exact (flat)* compares the query with all 20,000 vectors. It is the
    reference, so recall is 1.00 by definition, and it is the slowest.
  - *HNSW `ef=8`* explores few candidates: fastest, but recall dipped to 0.95
    (about 1 true neighbour in 20 missed). This is the "approximate" in ANN.
  - *HNSW `ef=32`* gets recall back to 1.00 at about the same speed: for this
    data, 32 is already enough.
  - *HNSW `ef=128`* is still 1.00 but slower. Extra effort bought nothing.
- **Filtered search** (`company_id = 3`, one of 7 fake companies, like our
  company scoping). Without a payload index Qdrant checks each candidate's
  `company_id` while walking the graph; with one it can jump to the matching
  points, so it is faster and recall stays 1.00.

What to take away:

1. ANN is already about 2x faster at 20,000 vectors, and the gap grows with
   size (millions of vectors show far larger gaps).
2. `ef` is a dial: raise it for accuracy, lower it for speed; past a point more
   effort only costs time.
3. If you filter on a field (like company), index that field.

Caveats: random clustered vectors can behave differently from real text
embeddings, timings are noisy (compare the ordering, not exact values), and
this says nothing about our own 16 documents, which are too few for an index
to matter. To see the gap widen, raise `N` in the script to 100,000.

### In a real system (how the app would use this at scale)

The demo generates fake rows because it only needs vectors to search. A real
app does not generate data; it already has documents and needs the same steps
our pipeline already follows, with a few changes at scale.

1. **Embed real chunks.** Documents are split into chunks and each chunk is
   embedded by the model (`embed_text` with `gemini-embedding-001`, 768 dims).
2. **Store them with a payload.** Each chunk becomes a Qdrant *point*: the
   vector plus a payload (document title, company id, chunk text, source path),
   so a hit can be cited without another database lookup
   (`upsert_chunks` in `app/rag/qdrant_store.py`).
3. **The index builds itself.** The app never calls an "index" function. Qdrant
   builds the HNSW graph in the background as points arrive (once a segment
   passes its indexing threshold). That is the `indexed_vectors_count` the demo
   waits on.
4. **Query time.** The question is embedded with the same model, then
   `query_points(..., query_filter=..., limit=top_k)` returns the nearest chunks
   (`retrieve_relevant_chunks` in `app/rag/retrieve.py`). We then drop anything
   below `MIN_SIMILARITY` and pass the rest to the LLM as numbered context.
   Search is approximate, but the LLM only needs the relevant chunks in the
   top few.
5. **Filtering.** Company scoping is a payload filter. Today we have no payload
   index on `company_id`, which is fine for 16 documents; at scale we would
   create one with `create_payload_index`, as the demo does.

What would have to change for a big corpus (our app is **not** built this way
yet):

- **Ingestion.** `recreate_collection()` deletes and rebuilds the whole
  collection on every ingest. That is fine for 16 files; at scale you would
  upsert only new or changed chunks and delete removed ones, and batch the
  uploads and embedding calls.
- **Tuning.** Keep the default HNSW settings until measurements say otherwise.
  Then pick `m`, `ef_construct` and per-query `hnsw_ef` by measuring recall@k
  and latency on **your own** questions, as the demo does on synthetic ones.
- **Memory.** Millions of 768-dim float vectors are large. Options are
  quantization (smaller numbers per dimension), keeping vectors on disk, or
  sharding across nodes.
- **Quality checks.** Keep a set of real questions with known right chunks and
  track recall@k (the Stage 6 promptfoo suite is the start of this), so index
  changes do not silently hurt answers.

## Implemented design

```text
Document -> parse (frontmatter + body) -> chunk (600 chars, 100 overlap)
         -> embed (Ollama mxbai-embed-large, 1024-dim) -> store (pgvector)
Question -> embed -> cosine similarity search (<=>) -> top chunks (>= 0.3 similarity)
         -> numbered context block -> LLM (grounded system prompt) -> answer + citations
```

- Vector storage: `pgvector` extension inside the existing PostgreSQL service
  (image switched to `pgvector/pgvector:pg17`). No ANN index yet — the corpus
  is small enough for an exact `<=>` scan; Stage 6 revisits indexing.
- Embeddings: local Ollama model `mxbai-embed-large`, called through
  `apps/api/src/rag/embeddings.ts`.
- Chunking: explicit character-based sliding window in
  `apps/api/src/rag/chunking.ts` (`CHUNK_SIZE=600`, `CHUNK_OVERLAP=100`),
  unit-tested in `chunking.test.ts`.
- Ingestion (`apps/api/src/rag/ingest.ts`): reads every `.md` file in
  `sample-data/documents/`, parses YAML frontmatter (`title`, `type`,
  optional `company`) with `gray-matter`, resolves `company` to an existing
  `companies.id`, truncates and re-inserts `documents`/`document_chunks` on
  each run, and records each run in `ingestion_runs`.
- Retrieval (`apps/api/src/rag/retrieve.ts`): embeds the question, runs a
  cosine-similarity query joining `document_chunks` → `documents` →
  `companies`, and builds a numbered, citable context block.
- Routes:
  - `POST /api/documents/ingest` — runs the full pipeline.
  - `GET /api/documents` — lists ingested documents with chunk counts.
  - `GET /api/documents/ingestion-runs` — ingestion history/debugging.
  - `POST /api/chat/rag` — grounded chat; returns `{ message, citations[] }`.
  - `POST /api/chat` — unchanged general chat from Stage 2 (now its own router).
- UI: an "Ingest documents" button, a "Use document knowledge (RAG)" toggle,
  and numbered citations (title, company, doc type, similarity score) shown
  under grounded answers.

Synthetic documents (`sample-data/documents/`) cover emails, call notes,
support conversations, and two product/service overviews, cross-referenced
with the three companies already in the CRM database — this sets up Stage 5's
DB + RAG linkage.

## Stage 3.a: scale-aware search (exact below a threshold, HNSW above)

`app/rag/retrieve.py` counts the points in the collection (cached for 60 s)
and picks the search path:

- fewer than `VECTOR_INDEX_MIN_POINTS` (default 10,000): `exact=True`, every
  vector is compared, so the result is always correct;
- at or above it: `hnsw_ef=VECTOR_HNSW_EF` (default 64), the approximate path.

Each query logs `vector_search strategy=exact|hnsw`, and
`GET /api/v1/documents/vector-search-info` shows the current choice.
Qdrant switches in a similar way internally; this makes the choice visible.
The 16-document sample corpus always takes the exact path.

To watch it switch, seed a separate fake collection (random vectors, so
answers are meaningless; only the path is real):

```bash
cd apps/api-py
uv run python ../../scripts/seed_fake_chunks.py --count 20000
# restart the API with QDRANT_COLLECTION=document_chunks_demo, then:
curl http://localhost:8001/api/v1/documents/vector-search-info
uv run python ../../scripts/seed_fake_chunks.py --clean
```

Limits: the 10,000 threshold and `ef=64` are starting points. On real data,
measure recall on your own questions before trusting them.

## Learning boundaries

- Explain and implement chunk size, overlap, embeddings, similarity scoring,
  retrieval, context construction, and citations explicitly.
- Keep document ingestion distinct from query-time retrieval.
- Add a way to inspect chunks and retrieved sources for debugging.
- Do not use tools/agent loops or hide the pipeline behind a broad framework.

## Acceptance criteria

A developer can ingest sample documents, ask a document-supported question, see
the answer’s citations, and verify the cited source text.

Verified: ingested 8 documents into 16 chunks; asked "Does the Fleet
Visibility package include alerting, and can alerts be set per customer?"
through `POST /api/chat/rag` and received a correct, cited answer referencing
the product overview and the matching support conversation.

## How to run the app

```bash
cd /home/devarapallim/Murali/git-personal/customer-compass
docker compose up -d db ollama
```

- **First time / fresh volume**: `db/init.sql` and `db/002-rag.sql` both run
  automatically (mounted as ordered init scripts).
- **Existing volume from before Stage 3** (already had `companies`,
  `contacts`, `deals`, `interactions`): the container image changes to
  `pgvector/pgvector:pg17`, but Postgres init scripts only run once against an
  empty data directory, so apply the new schema manually:

  ```bash
  docker exec -i customer-compass-db psql -U customer_compass -d customer_compass < db/002-rag.sql
  ```

Pull the models (once), then install and start the app:

```bash
docker exec customer-compass-ollama ollama pull qwen2.5:3b        # Stage 2 chat model
docker exec customer-compass-ollama ollama pull mxbai-embed-large # Stage 3 embedding model
npm install
npm run dev
```

This runs the API (`http://localhost:3001`) and the web UI
(`http://localhost:5173`) together.

## How to test manually

1. **API health check**
   ```bash
   curl -s http://localhost:3001/health
   # expect: {"status":"ok"}
   ```
2. **Ingest the sample documents**
   ```bash
   curl -s -X POST http://localhost:3001/api/documents/ingest | python3 -m json.tool
   ```
   Observe: `"status": "completed"`, `"documentsProcessed": 8`,
   `"chunksCreated": 16`. Then inspect what was stored:
   ```bash
   curl -s http://localhost:3001/api/documents | python3 -m json.tool
   ```
   Observe: 8 documents, each with `chunk_count: 2`, and `company_name` set for
   the 6 company-specific documents (`null` for the 2 product overviews).
3. **Ask a grounded question**
   ```bash
   curl -s -X POST http://localhost:3001/api/chat/rag \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"Does the Fleet Visibility package include alerting, and can alerts be set per customer?"}]}' \
     | python3 -m json.tool
   ```
   Observe:
   - `message` answers the question and includes bracketed citation markers
     like `[1]`, `[2]`.
   - `citations` is a non-empty array; each entry's `title`/`snippet` should
     plausibly support the claim in `message` (expect the "Fleet Visibility
     rollout package overview" and "Pre-sales support conversation on alerting
     limits" documents to appear with high `similarity`, roughly 0.7–0.85).
4. **Confirm ungrounded chat still works unaffected**
   ```bash
   curl -s -X POST http://localhost:3001/api/chat \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"Say hi in 5 words."}]}'
   ```
   Observe: a `message` field with no `citations` key.
5. **Browser walkthrough** — open `http://localhost:5173`:
   - The chat panel shows an "Ingest documents" button and a "Use document
     knowledge (RAG)" checkbox.
   - Click "Ingest documents" and observe the status line report documents and
     chunks ingested (matches step 2).
   - With the RAG checkbox **unchecked**, ask a general question — answered with
     no citations shown.
   - With the RAG checkbox **checked**, ask the Fleet Visibility question from
     step 3 — the assistant's reply should appear with a numbered citations list
     underneath it (title, company, doc type, similarity score).

## Inspecting the database with a visual tool

The CRM tables (`companies`, `contacts`, `deals`, `interactions`) and the RAG
tables (`documents`, `document_chunks`, `ingestion_runs`) all live in the
**same** `customer_compass` Postgres database (started via `docker-compose
up`) — there are not two separate databases to connect to.

Any Postgres client works (DBeaver, TablePlus, Adminer, `psql`). Connection
details:

| Field | Value |
| --- | --- |
| Host | `localhost` |
| Port | `5432` |
| Database | `customer_compass` |
| Username | `customer_compass` |
| Password | `customer_compass_dev` |
| SSL | disabled (local dev only) |

Quick CLI alternative:

```bash
docker exec -it customer-compass-db psql -U customer_compass -d customer_compass
```

```sql
\dt                          -- list all tables (CRM + RAG together)
SELECT * FROM documents;
SELECT id, document_id, chunk_index, left(content, 50) FROM document_chunks LIMIT 5;
SELECT * FROM ingestion_runs ORDER BY id DESC LIMIT 5;
```

## Developer note

Changed/added files:

- `docker-compose.yml` — `db` image switched to `pgvector/pgvector:pg17`;
  mounts `db/002-rag.sql`.
- `db/002-rag.sql` — pgvector extension, `documents`, `document_chunks`,
  `ingestion_runs` tables. Runs automatically only on a fresh volume; apply
  manually to an existing volume with
  `docker exec -i customer-compass-db psql -U customer_compass -d customer_compass < db/002-rag.sql`.
- `apps/api/src/rag/chunking.ts` (+ test), `embeddings.ts`, `ingest.ts`,
  `retrieve.ts`.
- `apps/api/src/routes/documents.ts`, `apps/api/src/routes/chat.ts` (extracted
  from `app.ts`, added the `/rag` grounded endpoint).
- `sample-data/documents/*.md` — 8 synthetic documents.
- `apps/web/src/main.tsx`, `apps/web/src/styles.css` — ingestion control, RAG
  toggle, citation rendering.
- `apps/api/package.json` — fixed the `test` script glob (`src/**/*.test.ts`
  silently matched only one directory level without bash `globstar`, so
  `app.test.ts` was never actually running; now wrapped with
  `bash -O globstar`).
