# Customer Compass API (Python)

# Customer Compass API (Python)

FastAPI service for the v2 stack — replaces the original Express API
(`apps/api`, removed in PR 5) one PR at a time. All frontend-facing routes
live under `/api/v1` (see `docs/tech-stack.md` for the overall migration
narrative); `/health` stays unprefixed.

- **PR 2**: app wiring, Postgres connectivity check (`/health`), Docker image.
- **PR 3**: document ingestion pipeline (`POST /api/v1/documents/ingest`) —
  parses `sample-data/documents/*.md`, chunks, embeds via Google's
  `gemini-embedding-001`, and stores chunk vectors + payload in Qdrant.
  Postgres keeps `documents`/`ingestion_runs` as ingestion metadata only.
- **PR 4**: chat/RAG/CRM routes and the LLM provider abstraction:
  - `POST /api/v1/chat` — general chat (no retrieval).
  - `POST /api/v1/chat/rag` — grounded chat; retrieves relevant chunks from
    Qdrant (with company-scoping via a `should`/`IsNullCondition` filter)
    and cites sources.
  - `POST /api/v1/chat/crm` — keyword-routed chat; pulls structured CRM
    facts (open deals, company summary) from Postgres, RAG chunks from
    Qdrant, or both, depending on `app/chat/router.py`'s `classify_query`.
  - `GET /api/v1/llm/models` — OpenRouter free/paid model catalog, TTL-cached.
  - Request validation: messages must be non-empty, ≤12 messages, each
    message's `content` must be ≤4000 chars and non-blank after trimming.
    FastAPI returns `422` for validation errors (a framework default,
    unlike the old Express API's `400`).
- **PR 5**: company routes (`GET /api/v1/companies`, `GET
  /api/v1/companies/{id}`) ported, frontend cut over to this service, and
  the old Express API (`apps/api`) removed entirely.

## Local development

```bash
cd apps/api-py
uv sync                 # installs dependencies into .venv
cp .env.example .env    # then edit: DATABASE_URL, QDRANT_URL, GOOGLE_API_KEY, OLLAMA_URL/OPENROUTER_API_KEY
uv run uvicorn app.main:app --reload --port 8001
```

Requires Postgres, Qdrant, and Ollama running: `docker compose up -d db
qdrant ollama` (from the repo root). Get a free `GOOGLE_API_KEY` at
https://aistudio.google.com/apikey — needed for `/api/v1/documents/ingest`
(not for `/health`). Get a free `OPENROUTER_API_KEY` at
https://openrouter.ai/keys — needed only for `provider: "cloud"` requests or
`LLM_PROVIDER=cloud`.

## Verify

```bash
curl -s http://localhost:8001/health
# {"status":"ok"}

curl -s http://localhost:8001/api/v1/companies
curl -s http://localhost:8001/api/v1/companies/1

curl -s -X POST http://localhost:8001/api/v1/documents/ingest
# {"ingestionRunId":1,"documentsProcessed":8,"chunksCreated":16,"status":"completed"}

curl -s http://localhost:8001/api/v1/documents
curl -s http://localhost:8001/api/v1/documents/ingestion-runs

curl -s -X POST http://localhost:8001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}]}'
# {"message":"...","provider":"ollama"}

curl -s -X POST http://localhost:8001/api/v1/chat/rag \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is our refund policy?"}]}'
# {"message":"...","citations":[...],"provider":"ollama"}

curl -s -X POST http://localhost:8001/api/v1/chat/crm \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Tell me about Acme Corp"}]}'
# {"message":"...","facts":{...},"citations":[...],"scopedCompany":"Acme Fabrication","provider":"ollama"}

curl -s http://localhost:8001/api/v1/llm/models
# {"free":[...],"paid":[...]}
```

## Tests

```bash
uv run pytest
```

`tests/test_ingest.py` is skipped automatically if `GOOGLE_API_KEY` isn't set
in the environment (it needs a live embedding call). `tests/test_chat_router.py`
covers `classify_query`'s keyword/company-matching logic with a stubbed
`list_companies()` — no network required.
