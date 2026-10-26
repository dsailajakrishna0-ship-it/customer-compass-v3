# V2 baseline — stage documents (frozen)

These are the Stage 1–10 records from `customer-compass-v2` (tag `v2-final`). They describe how each piece was **hand-built** in V2 and are kept as the learning baseline; V3 stages in [`../roadmap.md`](../roadmap.md) replace the code they describe. Do not update them except to fix broken links. Current run and test steps are in [`../testing-guide.md`](../testing-guide.md).

| Part | Stages | Folder |
| --- | --- | --- |
| I — Foundations | 1 CRM foundation, 2 First LLM chat, 3 Basic RAG | [`part-1-foundations/`](part-1-foundations/) |
| II — Grounded Intelligence | 4 Cloud LLM provider, 5 Realistic CRM RAG, 6 Retrieval evaluation | [`part-2-grounded-intelligence/`](part-2-grounded-intelligence/) |
| III — Trust & Safety | 7 Production concerns, 8 Prompt-injection guardrails | [`part-3-trust-safety/`](part-3-trust-safety/) |
| IV — Autonomy & Protocols | 9 Tool calling via MCP, 10 Agentic assistant | [`part-4-autonomy-protocols/`](part-4-autonomy-protocols/) |

Also here: [`testing-walkthrough.md`](testing-walkthrough.md), a guided Ask / Observe / Learn path through the ten stages.

## Reading notes (moved here from the top of individual stage documents)

Stages 1–6 were written against the original Express API (`apps/api`, port 3001, `/api/...`). The code now has a FastAPI service (`apps/api-py`, port 8001, `/api/v1/...`). Paths, ports and curl examples inside those stages are kept as originally recorded.

**01-foundation.md**

> **v2 stack note:** this record was written against the original Express API
> (`apps/api`, port 3001, `/api/...`, `npm run dev` starting the API). In the
> current repo the API is FastAPI (`apps/api-py`, port 8001, `/api/v1/...`);
> start it with `docker compose up -d db qdrant ollama api-py` (Postgres for CRM data, Qdrant vector DB, Ollama local model runner, the FastAPI backend) and the web app
> with `cd apps/web && npm run dev`. See [../testing-guide.md](../testing-guide.md)
> for current run/test steps. Paths, ports and curl examples below are kept as
> originally recorded.

**02-first-llm-chat.md**

> **v2 stack note:** this record was written against the original Express API
> (`apps/api`, port 3001, `/api/...`). In the current repo the API is FastAPI
> (`apps/api-py`, port 8001, `/api/v1/...`; container `customer-compass-v3-ollama`, i.e. Ollama, which runs the local
> *generating* model `qwen2.5:3b` that writes the chat answers).
> See [../testing-guide.md](../testing-guide.md) for current run/test steps.
> Paths, ports and curl examples below are kept as originally recorded.

**03-basic-rag.md**

> **v2 stack note:** this record describes the original v1 implementation
> (Express API on port 3001, Ollama `mxbai-embed-large` embeddings, pgvector).
> In v2 the API is FastAPI (`apps/api-py`, port 8001, `/api/v1/...`,
> files `app/rag/*.py`), embeddings are Google `gemini-embedding-001`
> (768-dim; an embedding model that turns text into vectors, not a chat model)
> and vectors live in Qdrant (a vector database). See
> [../architecture.md](../architecture.md) and [../tech-stack.md](../tech-stack.md).
> Paths, ports, models and curl examples below are kept as originally recorded.

**04-cloud-llm-provider.md**

> **v2 stack note:** file paths below (`apps/api/src/*.ts`) and URLs
> (`localhost:3001/api/...`) are from the original Express API. Current
> equivalents: `apps/api-py/app/llm/{provider,cloud,ollama}.py`,
> `apps/api-py/app/routes/llm.py`, `http://localhost:8001/api/v1/...`.
> Since Stage 7, `provider.py` also retries once on the other provider.

**05-realistic-crm-rag.md**

> **v2 stack note:** file paths below (`apps/api/src/*.ts`) and URLs are from
> the original Express API. Current equivalents: `apps/api-py/app/crm/queries.py`,
> `app/chat/router.py` (the query router that picks DB facts, documents, or both), `app/rag/retrieve.py`, `app/routes/chat.py`, served at
> `http://localhost:8001/api/v1/chat/crm`. `chat/citations.ts` was not ported
> (citation shaping lives in `routes/chat.py`). Tests: `cd apps/api-py && uv run pytest`.
