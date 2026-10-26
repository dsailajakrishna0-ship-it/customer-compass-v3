# Developer commands. Install just once: `uv tool install rust-just` (or your package manager).
# Run `just` to list them.

set shell := ["bash", "-euo", "pipefail", "-c"]

api := "apps/api-py"

# list the recipes
default:
    @just --list

# start the core stack (db, vector store, local model, api)
up:
    docker compose up -d db qdrant ollama api-py

# stop the stack (data volumes are kept)
down:
    docker compose down

# start only Postgres and wait until it is healthy (what the API tests need)
db:
    docker compose up -d --wait db

# lint, format check and type check, Python then web
lint:
    cd {{api}} && uv run ruff check .
    cd {{api}} && uv run ruff format --check .
    cd {{api}} && uv run mypy
    npm run lint
    npm run typecheck

# apply auto-fixes and formatting
fmt:
    cd {{api}} && uv run ruff check --fix .
    cd {{api}} && uv run ruff format .

# all tests
test: test-api test-web

# API tests with coverage (needs Postgres, started for you)
test-api: db
    cd {{api}} && uv run pytest -q --cov --cov-report=term-missing:skip-covered

# web tests
test-web:
    npm test

# production build of the web app
build:
    npm run build

# load the sample documents into the vector store (stack must be up)
seed:
    curl -fsS -X POST http://localhost:8001/api/v1/documents/ingest

# retrieval evals (stack must be up and seeded); see evals/README.md
eval:
    cd evals && OLLAMA_BASE_URL=http://localhost:11435 npx promptfoo@latest eval -c promptfooconfig.yaml
