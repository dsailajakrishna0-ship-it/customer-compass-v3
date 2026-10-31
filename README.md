# Customer Compass V3

[![CI](https://github.com/dsailajakrishna0-ship-it/customer-compass-v3/actions/workflows/ci.yml/badge.svg)](https://github.com/dsailajakrishna0-ship-it/customer-compass-v3/actions/workflows/ci.yml)

A small-business CRM used as an **AI learning project**: chat over CRM facts and documents (🟪RAG), 🟪tool calling over 🟦MCP, 🟪prompt-injection 🟪guardrails, evaluation, and a 🟪human-in-the-loop 🟪agent. All data is synthetic.

V3 starts fresh, seeded from [`customer-compass-v2`](https://github.com/dsailajakrishna0-ship-it/customer-compass-v2) (tag `v2-final`), where every piece was hand-built to learn the mechanics. V3 replaces that hand-written plumbing with open-source frameworks (🟦LangGraph, 🟦LiteLLM, 🟩Qdrant, 🟦Langfuse and others) one stage at a time, measuring each change against a saved baseline. The plan is in [docs/roadmap.md](docs/roadmap.md).

> **Status:** Stage 0 (foundation) in progress. The code is still the V2 seed; the frameworks arrive from Stage 1 on.

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](docs/ai-terms.md)

## How it fits together

![Architecture overview: the React and Vite web UI calls the FastAPI API over HTTP. The API reads and writes Postgres (CRM data, tasks, audit log) and Qdrant (document vectors), calls LLM providers for chat and embeddings, and uses MCP tools for CRM, documents and tasks.](docs/img/diagrams/readme-how-it-fits-together.png)

<sub>Diagram source: [readme-how-it-fits-together.mmd](docs/diagrams/readme-how-it-fits-together.mmd)</sub>

Details: [docs/architecture.md](docs/architecture.md). Technology choices: [docs/tech-stack.md](docs/tech-stack.md).

## Quick start

Requires Docker, Node.js and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/dsailajakrishna0-ship-it/customer-compass-v3.git
cd customer-compass-v3

cp .env.example .env              # add two free keys: GOOGLE_API_KEY (embeddings) and OPENROUTER_API_KEY (chat models)
docker compose up -d db qdrant api-py

npm ci
npm run dev                       # web app at http://localhost:5173
```

The `migrate` service creates the database schema and demo CRM data automatically before the API starts.

Tool-calling chat talks to an 🟦MCP tool server: the Python one (`mcp-fastmcp`) starts with the stack. To also run the Java twin, `just up-java` (Spring Boot, port 8003); the web app's **Tool server** radio buttons then let you choose. Both are checked against [`contracts/mcp-tools.json`](contracts/mcp-tools.json).

> Upgrading from a V2-style database volume? Recreate it once: `docker compose down -v` (this also removes the 🟩Qdrant volume, so you will ingest the documents again), then `up` again. To keep the volumes, run `uv run alembic stamp 0002` then `uv run alembic upgrade head` in `apps/api-py` instead. Then open the app and click **Ingest documents** once. API docs are at <http://localhost:8001/docs>. Full run and test guide, with every chat mode and sample questions: [docs/testing-guide.md](docs/testing-guide.md). Problems starting up: [docs/troubleshooting.md](docs/troubleshooting.md).

## Developer commands

Install [just](https://just.systems/) once (`uv tool install rust-just`), then:

```bash
just            # list all commands
just lint       # ruff, mypy, ESLint, tsc
just test       # API tests (starts Postgres) and web tests
just fmt        # auto-fix and format Python
just up         # start the stack      just down   # stop it
```

Optional: `uv tool install pre-commit && pre-commit install` to run the checks on every commit. A Dev Container with everything installed is in `.devcontainer/`. Tool choices: [ADR 0002](docs/adr/0002-developer-tooling.md).

## Releases

Pushing a tag such as `v3.0.0-alpha.1` publishes the API and web images to GitHub Container Registry and creates a GitHub Release ([ADR 0004](docs/adr/0004-release-and-image-publishing.md)).

## Repository layout

| Path | What is in it |
| --- | --- |
| `apps/web` | React + Vite + TypeScript UI |
| `apps/api-py` | FastAPI service: chat, 🟪RAG, CRM queries, 🟪guardrails, 🟦MCP tools, 🟪agent |
| `apps/api-py/migrations` | Alembic database migrations: schema and synthetic demo data |
| `sample-data` | Synthetic CRM documents |
| `evals` | 🟦promptfoo evaluation suites |
| `docs` | Plan, architecture, decisions, guides, and the frozen V2 stage records |

## Documentation

Start at [docs/README.md](docs/README.md). New to AI words? Every AI term in the docs is marked with a coloured square and explained in the [A to Z list](docs/ai-terms.md). **Learn the concepts:** one guide per stage in [docs/stages/](docs/stages/README.md), starting with [Stage 0](docs/stages/00-foundation.md). Plan: [docs/roadmap.md](docs/roadmap.md). Decisions: [docs/adr/](docs/adr/README.md). The hand-built V2 learning record: [docs/v2-baseline/](docs/v2-baseline/README.md).

## Contributing

One pull request per roadmap sub-stage; `main` is protected. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Licensed under the [MIT License](LICENSE).
