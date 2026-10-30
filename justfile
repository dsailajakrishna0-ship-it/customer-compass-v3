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

# apply database migrations to the local Postgres (DATABASE_URL overrides the target)
migrate:
    cd {{api}} && uv run alembic upgrade head

# API tests with coverage (needs Postgres, started and migrated for you)
test-api: db migrate
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

# reproduce the saved baseline (evals/baseline/v2.json); stack must be up and seeded, see evals/README.md
eval:
    uv run --project {{api}} python evals/run_eval.py --check evals/baseline/v2.json

# measure all suites and overwrite the saved baseline (do this only on purpose)
eval-baseline:
    uv run --project {{api}} python evals/run_eval.py --out evals/baseline/v2.json

# offline suite only: the rule-based guard against the adversarial prompts (no stack needed)
eval-offline:
    uv run --project {{api}} python evals/run_eval.py --suites adversarial

# the older promptfoo suite (needs the stack and an Ollama judge model); see evals/README.md
eval-promptfoo:
    cd evals && OLLAMA_BASE_URL=http://localhost:11435 npx promptfoo@latest eval -c promptfooconfig.yaml

# render docs/diagrams/*.mmd to docs/img/diagrams/*.png (needs Docker; the first run pulls a ~2.4 GB image)
diagrams:
    for f in docs/diagrams/*.mmd; do n=$(basename "$f" .mmd); docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/docs":/data ghcr.io/mermaid-js/mermaid-cli/mermaid-cli:12.0.0 -p /data/diagrams/mermaid-puppeteer.json -i "/data/diagrams/$n.mmd" -o "/data/img/diagrams/$n.png" -s 2 -b white || exit 1; echo "rendered $n"; done

# apply the AI colour code to the docs and regenerate docs/ai-terms.md (edit docs/ai-terms.yaml first)
ai-terms:
    uv run --project {{api}} python scripts/ai_terms.py write

# fail if the docs or docs/ai-terms.md are out of date with docs/ai-terms.yaml (CI runs the same check)
ai-terms-check:
    uv run --project {{api}} python scripts/ai_terms.py check
