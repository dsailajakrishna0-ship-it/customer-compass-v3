# v2 startup — known issues & lessons learned

Notes from the first real local run of `customer-compass-v2`, right after the
infra migration PR (Qdrant, the vector DB + Ollama, the local model runner, cache reuse). Keep this updated as new
startup quirks are found — especially while v1 (`customer-compass`) and v2
coexist on the same machine.

## User guide — how to use "Ask Compass"

A walkthrough of the chat experience: what each control does, when to use
each mode, and example questions to try.

### 1. Open the app

- Go to `http://localhost:5173`, click **Chat** in the nav bar — this opens
  the "Ask Compass" panel.
- Click **Ingest documents** once per fresh environment (top-left button).
  This chunks + embeds the sample CRM documents into the vector store so
  RAG/CRM modes have something to retrieve. You only need to do this again
  if the database/vector store is reset.

### 2. Choose a Chat mode — what each one is *for*

| Mode | What it does | When to use it |
|---|---|---|
| **General chat** | Plain LLM conversation, no CRM data at all | Quick sanity-check that the model itself is reachable; general knowledge questions unrelated to this CRM |
| **Document knowledge (RAG)** | Answers are grounded only in ingested documents (emails, notes), with numbered citations | "What did we discuss with this customer?" type questions — anything that should be backed by a real document |
| **CRM copilot (facts + documents)** | Combines live structured database facts (deals, pipeline) *and* cited documents, clearly separated | The most realistic "assistant" experience — ask about deals/status *and* conversation history in one question |
| **Tool calling (MCP)** | The model calls live tools mid-conversation (company summary, open deals, document search) and can propose a follow-up task that you confirm in your next message | "Create a follow-up task for Acme" style requests; see [Stage 9](part-4-autonomy-protocols/09-tool-calling-mcp.md) |

### 3. Choose a Model

- **Local (Ollama · qwen2.5:3b)** — runs fully offline on your machine, no
  API key needed, consistent but slower on CPU.
- **Cloud (OpenRouter, free tier)** — faster, needs `OPENROUTER_API_KEY` set
  in `apps/api-py/.env` (and in root `.env` / `docker-compose.yml`'s
  `api-py` environment if running the full containerized stack); a third
  dropdown lets you pick the specific free model. Free models can
  occasionally return an empty/rate-limited response (see issue #6 below)
  — just retry or switch models.

There is **no separate company selector** in the UI — you simply name the
company in your question text (e.g. "Acme Fabrication"), and the app scopes
retrieval to that company automatically. Seeded companies: **Acme
Fabrication**, **Northstar Logistics**, **Harbor & Pine**, **Vertex
Analytics**, **Golden Valley Foods**, **Summit Builders**, **Riverside
Health Group**.

### 4. Example questions per mode

See [testing-guide.md](testing-guide.md) — it lists sample questions and
expected results for every mode × provider combination.

## Issues seen so far

### 1. `db` container name clash with v1 (fixed)


**Symptom:** UI shows *"Could not reach the API. Start PostgreSQL and the
API, then refresh."* even though the API process is running.

**Cause:** v2's `docker-compose.yml` initially reused v1's exact container
name (`customer-compass-db`). If a stopped v1 `customer-compass-db` container
already exists on the machine, `docker compose up` fails to (re)create v2's
`db` with the same name — and depending on compose version, this can abort
the whole `up` command partway (see #2 below).

**Fix applied:** v2's `db` container is now named `customer-compass-v2-db`,
matching the naming already used for `ollama`/`qdrant`. No action needed
going forward — just make sure you're on a version of this repo that
includes that fix.

### 2. A failed service can silently abort the whole `docker compose up`

**Symptom:** You ran `docker compose up -d db qdrant ollama`, but afterwards
`ollama` (or another service) wasn't actually running — `docker ps` shows
nothing, or `docker ps -a` shows it stuck in `Created` state (never
`Started`).

**Cause:** If one service in the same `up` command fails to create (e.g. the
container-name clash in #1), some Docker Compose versions skip starting the
remaining services in that invocation entirely, even though they report
"Created" successfully.

**Lesson:** After *any* `docker compose up`, don't just trust the command's
output — verify all expected containers are actually in the `Up` state:
```bash
docker ps --format "{{.Names}}\t{{.Status}}"
```
If something is missing or stuck at `Created`, re-run `docker compose up -d
<missing-service>` explicitly for just that service.

### 3. Full startup needs three containers, not just `db`

The API depends on **all three** infra containers — Postgres, Qdrant, and
Ollama. Starting only `db` will let the API process boot, but any chat
request will fail (500/503) because Ollama (generation) isn't reachable.

Always start all three together:
```bash
docker compose up -d db qdrant ollama
```

### 4. v1 and v2 can't run `db`/`ollama` at the same time

Both repos' Postgres and Ollama services bind the **same host ports** (5432,
11435) regardless of container name. Only one stack (v1 or v2) can have
these services running at once — stop one (`docker compose down`) before
starting the other.

### 5. `apps/api-py/.env` is per-repo, not shared

v1 (Express, `apps/api/.env`) and v2 (FastAPI, `apps/api-py/.env`) have
separate, gitignored env files — and v2's own file isn't the same one
Docker Compose reads either (that's the root `.env`, for variable
substitution in `docker-compose.yml`). Setting `OPENROUTER_API_KEY` in one
does **not** automatically apply to the others — copy it over manually if
reusing the same key:
```bash
cp ../customer-compass/apps/api/.env apps/api-py/.env
# and/or add it to the repo-root .env if running via docker-compose
```
Then restart the service (`docker compose up -d --build api-py`, or
`uv run uvicorn app.main:app --reload --port 8001` for local dev) — env
vars are loaded once at process start, not hot-reloaded on `.env` changes.

### 6. Free-tier OpenRouter cloud models are inconsistent — not a bug

Occasionally picking a free OpenRouter model returns *"The cloud model
returned an empty response. Try again or pick a different model."* This is
expected: free-tier models route through shared, rate-limited community
infrastructure and can return a `200 OK` with no actual content. The app
already distinguishes this case from a hard error (see
`apps/api-py/app/llm/cloud.py`). If it happens, just retry or pick a
different model from the dropdown — it isn't specific to v2.

### 7. Dropdown "selected value" can look wrong due to shared browser storage

v1 and v2 both run on `localhost:5173` (same origin). Chat mode / provider /
cloud-model selections are persisted to `localStorage`, which is shared by
origin, not by repo — so a selection made while testing v1 can appear as the
"default" when you later open v2 in the same browser. Clear it if needed:
```js
localStorage.clear()
```
(Removing this persistence entirely, or namespacing the storage keys per
repo, is a possible follow-up — not yet done as of this PR.)
