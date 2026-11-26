# Hand test: the same three questions, every backend (about 20 minutes with keys)

One page for when you have time. It runs the **application** and the **comparison-lab backends** (`comparisons/`, ports 191xx) on the **same three questions**, so you can compare what they say. **Nothing in the lab has been run against a live model yet**: this page is how that first run happens. Everything is read-only against the demo data; nothing is written except the lab's own scratch collection `compare_withlangchain` (and the Java edition's, if you run it).

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](ai-terms.md)

**Needs:** Docker, `just`, `uv`, and your own keys (`OPENROUTER_API_KEY`, and `GOOGLE_API_KEY` for the document parts) in `.env`. **Never paste a key into a chat, an issue or a commit.** Without keys you can still run Part 1 and see that every backend refuses politely.

## The three questions

| | Question (or company) | What a good answer shows |
| --- | --- | --- |
| **Q1** | `What deals does Acme Fabrication have?` | the open deal **Premium Operations Plan renewal**, 48000.00 (from the demo data), and a `toolsUsed` entry |
| **Q2** | `What did Acme Fabrication say about the volume discount?` | an answer from the **documents** (the Acme call and email notes), with citations or hits from files named `acme-...` |
| **Q3** | `What deals does Nobody Ltd have?` | **no invented deals**: a "not found" style answer, and no deal names |

## Part 0: get ready (5 minutes, once)

From the repository root (`customer-compass-v3`):

1. `cp .env.example .env` if you have no `.env`, remove the `# ` before the two key lines and paste your keys.
2. `just up` (database, Qdrant and the application on <http://localhost:8001>); check `curl -s localhost:8001/health`.
3. Ingest the demo documents once: `curl -s -X POST localhost:8001/api/v1/documents/ingest` (expect **19 documents, 33 chunks**).
4. Load the keys into this terminal without printing them: `set -a; . ./.env; set +a`.

The lab backends talk to the application on port 8001 for the CRM data and (for ingestion and retrieval) to the Qdrant of `just up` on port 6333, so give them `CRM_BASE_URL=http://localhost:8001` (the default) and `QDRANT_URL=http://localhost:6333`.

## Part 1: no keys (3 minutes): do they refuse politely?

Start one lab backend and ask a question without a key: `OPENROUTER_API_KEY= just comparisons-tool-calling-with-langchain` (second terminal), then `curl -s -X POST localhost:19101/api/v1/chat/tools -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"hi"}]}'`. **Look for:** a 503 saying the key is not set, and **no stack trace and no key text**. Stop it with Ctrl+C.

## Part 2: the application, then the lab (Q1 to Q3)

**The application first (the reference)**, with the web app (`cd apps/web && npm ci && npm run dev`, <http://localhost:5173>) or with curl:

| Question | Command |
| --- | --- |
| Q1 | `curl -s -X POST localhost:8001/api/v1/chat/tools -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"What deals does Acme Fabrication have?"}]}'` |
| Q2 | `curl -s -X POST localhost:8001/api/v1/chat/rag -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"What did Acme Fabrication say about the volume discount?"}]}'` |
| Q3 | the Q1 command with `Nobody Ltd` instead of `Acme Fabrication` |

**The lab backends** (each in its own terminal with the keys loaded; stop with Ctrl+C):

| Module | Start | Ask | Look for |
| --- | --- | --- | --- |
| **Tool calling, LangChain** | `just comparisons-tool-calling-with-langchain` (19101) | the Q1 command with port **19101** | `toolsUsed` lists `get_open_deals` or `get_company_summary`; the deal named above; `mcpServer` is `withLangChain` |
| **Tool calling, LangGraph** | `just comparisons-tool-calling-with-langgraph` (19102) | port **19102** | the same answer in its own words |
| **Ingestion** | `QDRANT_URL=http://localhost:6333 just comparisons-ingest-with-langchain` (19111) | `curl -s -X POST localhost:19111/api/v1/ingest -d '{"limit":3}' -H 'Content-Type: application/json'`, then without a limit | `embeddingRequests` is **1**; chunks about 29 for the full run; run it twice: the count does not grow |
| **Retrieval** | `QDRANT_URL=http://localhost:6333 just comparisons-retrieve-with-langchain` (19121) | `curl -s -X POST localhost:19121/api/v1/retrieve -H 'Content-Type: application/json' -d '{"query":"What did Acme Fabrication say about the volume discount?"}'` | `hits` best first, each `score` **at or above 0.60**, `source` files starting `acme-`; `considered` against `kept` |

Repeat **Q3** on 19101 and 19102: **no deal names** in the answer.

## Part 3: the pause, the memory and the teams (10 minutes)

| Module | Start | Ask | Look for |
| --- | --- | --- | --- |
| **Agent, LangGraph** | `just comparisons-agent-with-langgraph` (19141) | `curl -s -X POST localhost:19141/api/v1/agent/start -H 'Content-Type: application/json' -d '{"company":"Acme"}'`, then `.../agent/resume` with `{"runId":"<id>","approve":true}` | status `awaiting_approval` with one recommendation; after approval a **dry-run** message ("Nothing was written"); resume the same run again: **409** |
| **Agent, LangChain** | `just comparisons-agent-with-langchain` (19142) | the same on 19142 | the same shape; the model decides the steps, so **tell me if it ever skips the pause** |
| **Memory** | `just comparisons-memory-with-langgraph` (19161) | `curl -s -X POST localhost:19161/api/v1/conversations`, then two turns at `/api/v1/chat/memory` with that `conversationId` (`My name is Maya.` then `What is my name?`) | the second answer knows the name; `memory.messagesUsed` is **2**, `messagesStored` **4**; try 19162 too |
| **Teams** | `just comparisons-multi-agent-supervisor` (19151), `-handoff` (19154), `-network` (19153), `-hierarchical` (19152) | `curl -s -X POST localhost:1915x/api/v1/multi-agent/run -H 'Content-Type: application/json' -d '{"company":"Acme"}'` | `decisions`: who decided (`code` or the model), anything the model proposed that was replaced, `turns`; compare the four on the same company |

**Observation (optional):** start `TELEMETRY_ENABLED=true just comparisons-observe-with-langchain` (19131), ask Q1, then open `localhost:19131/api/v1/observability/recent`: spans per model call and per tool, token counts, **no question or answer text**.

## Part 4: the Java twin (optional, 10 minutes)

Stop the Python application first (`docker compose stop api-py`): the Java API also uses port 8001. In the Java repo (`customer-compass-v3-java`): `just db`, `just qdrant`, export the keys, `just run`, then `just crm "What deals does Acme Fabrication have?"` and `just rag "What did Acme Fabrication say about the volume discount?"`. **Look for** the same deal and the same documents as in Part 2. The Java comparison backends (`comparisons/`, ports 181xx) are listed in that repo's `comparisons/README.md`.

## What to write down

For each backend: the answer in one line, anything **invented** (a deal or a quote that is not in the data), anything **missing** (the Premium Operations Plan renewal), and any **error text** that shows a key, a URL or a library message (there should be none). Send me the differences and I will turn them into the first real measurements, and update the lab's "not measured" list.

## What this test can and cannot tell you

**The sample data is small, tidy and invented.** It is **16 short Markdown notes** (calls, emails and support notes) about **7 made-up companies** (Acme Fabrication, Golden Valley Foods, Harbor & Pine, Northstar Logistics, Riverside Health Group, Summit Builders, Vertex Analytics), plus one PDF, one Word file, one spreadsheet and a separate farm-supply handbook. It contains no real customer or employer material. A tidy corpus makes retrieval look easier than real company documents would, so:

- **A good result here proves the plumbing** (the contract, the limits, the order of operations, the refusals), **not answer quality on real documents.**
- **Three questions are a spot check, not an evaluation.** The replayable comparisons (`just eval-judged`, `eval-multi`, `eval-frameworks`) are the measured ones, and they too run on this data.
- To test on realistic material, add your own **non-confidential** notes to `sample-data/documents/` with front matter (`title`, `type`, `company`, `date`); the `company` must match a CRM company name **exactly** or the note is not linked to a company; then re-run ingestion (`POST /api/v1/documents/ingest`).
