# Stage 4 — Cloud LLM provider option

**Part:** II — Grounded Intelligence
**Status:** Implemented

> **v2 stack note:** file paths below (`apps/api/src/*.ts`) and URLs
> (`localhost:3001/api/...`) are from the original Express API. Current
> equivalents: `apps/api-py/app/llm/{provider,cloud,ollama}.py`,
> `apps/api-py/app/routes/llm.py`, `http://localhost:8001/api/v1/...`.
> Since Stage 7, `provider.py` also retries once on the other provider.

## Goal

Add one free-tier cloud LLM provider as a swappable alternative to local Ollama (the runner of the local generating model),
without replacing it. This turns the "future cloud-model providers" boundary
noted since Stage 2 into a real, working option, and gives later stages
(evaluation, production fallback) a second real provider to compare against
instead of a hypothetical one.

## Why this stage exists here

- Stages 1–3 already built the model-calling plumbing (`/api/chat`,
  `/api/chat/rag`) behind a server-side boundary — adding a second provider is
  a natural, low-risk extension of that same code path.
- Stage 6 (retrieval evaluation) benefits from comparing local vs. cloud
  answer quality/latency on the same benchmark.
- Stage 7's "model fallback" (production concerns) needs a real second
  provider to fall back to, not just a design placeholder.

## Chosen provider (free tier)

**OpenRouter** (a gateway that gives access to hosted cloud generating models) — OpenAI-compatible `/chat/completions` API with a rotating
catalog of `:free`-suffixed models. Chosen over Groq/Gemini for this stage
because its request/response shape matches Ollama's closely enough that one
thin adapter (`cloud.ts`) covers it, and its free-tier model list is fetchable
live (see `.env.example`) so the doc doesn't go stale when a model is retired.

Default model in use: `liquid/lfm-2.5-2.6b:free`.
OpenRouter's free models change often (promoted to paid, or temporarily
rate-limited under shared-pool contention) — if cloud requests start failing,
refresh the live list and swap the model in `.env` and `cloud.ts`'s fallback.

## Actual design (implemented)

```text
POST /api/chat, /api/chat/rag   { messages, provider?, model? }
GET  /api/llm/models            -> { free: [...], paid: [...] }
        |
        v
apps/api/src/llm/provider.ts   generate(systemPrompt, messages, provider?, model?)
        |              \
        v               v
  ollama.ts          cloud.ts (OpenRouter, model overridable per request)
```

- `apps/api/src/llm/provider.ts` exposes `generate()`, used by both chat
  routes. Provider is chosen **per request**, not just at server start:
  - If the request body includes `provider`, that value is used (validated
    server-side via `resolveProvider()` in `chat.ts`).
  - If omitted, it falls back to `DEFAULT_LLM_PROVIDER`, derived from the
    `LLM_PROVIDER` env var (defaults to `ollama`), so existing clients/tests
    that don't send `provider` see no behavior change.
- The web UI (`apps/web/src/main.tsx`) adds a "Model" `<select>` next to the
  RAG toggle — **Local (Ollama · qwen2.5:3b)** or **Cloud (OpenRouter, free
  tier)** — so the user can switch providers live, per message, with no
  restart. Each response is sent back with `provider: "ollama" | "cloud"` and
  the UI shows a small tag under the assistant message indicating which one
  answered.
- When "Cloud" is selected, a **second dropdown** ("OpenRouter model")
  appears, populated live from `GET /api/llm/models`:
  - **Free** models (all current `:free`-suffixed OpenRouter models) are
    selectable — the user can pick any of them per message, since OpenRouter's
    free roster rotates and some models get rate-limited under shared load.
  - **Paid** models (a couple of well-known examples, e.g. GPT-4o-mini,
    Claude Sonnet 4) are listed but rendered **disabled/greyed out** — shown
    for learning/reference only, never selectable, so no request can
    accidentally incur cost.
  - The chosen model is sent as `model` in the request body; `generateWithCloud`
    uses it instead of the server's `OPENROUTER_MODEL` default for that one
    request. `GET /api/llm/models` is cached server-side for 5 minutes to
    avoid hammering OpenRouter's public catalog endpoint.
- System prompts, validation, and message-history logic in the routes are
  unchanged; only the model-calling boundary is swapped.
- The cloud API key lives in `apps/api/.env` (gitignored), documented in
  `.env.example`.

## Non-goals (deferred to later stages)

- No automatic fallback logic between providers yet (Stage 7).
- No cost/latency benchmarking framework yet (Stage 6 covers evaluation).
- Only one cloud provider wired (OpenRouter); adding Groq/Gemini later is a
  matter of adding another file next to `cloud.ts` and a new `LlmProvider`
  union member — the UI `<select>` and `provider.ts` dispatch are already
  built to support more than two options.

## Acceptance criteria

The same `/api/chat` and `/api/chat/rag` requests produce a comparable answer
whether `provider: "ollama"` or `provider: "cloud"` is sent in the request
body (or omitted, defaulting to `ollama`), with no restart required to switch
between them.

## How to run the app

```bash
cd /home/devarapallim/Murali/git-personal/customer-compass
docker compose up -d db ollama
cd apps/api
cp .env.example .env
# edit .env: set OPENROUTER_API_KEY to your own free key from
# https://openrouter.ai/keys (LLM_PROVIDER can stay "ollama" — it's just
# the default when a request omits `provider`)
cd ../..
npm install
npm run dev
```

This starts both the API (`http://localhost:3001`) and the web app
(`http://localhost:5173`). No env var changes or restarts are needed to
switch providers afterwards — that's done live from the UI or per request.

## How to test manually

1. **Browser walkthrough (recommended)** — open `http://localhost:5173`,
   pick **Local (Ollama)** in the "Model" dropdown, ask a question, then
   switch the dropdown to **Cloud (OpenRouter)** and ask again *without
   restarting anything*. Confirm the small provider tag under each answer
   matches your selection. With "Cloud" selected, a second **"OpenRouter
   model"** dropdown appears — free models are selectable, and the couple of
   paid examples are greyed out/disabled. Pick a different free model and
   confirm the answer still comes back correctly.
2. **List available cloud models via curl**
   ```bash
   curl -s http://localhost:3001/api/llm/models | python3 -m json.tool
   ```
   Expect a `free` array (all current OpenRouter `:free` models) and a `paid`
   array (a couple of reference-only examples the UI disables).
3. **Local provider via curl (default/no regression)**
   ```bash
   curl -s -X POST http://localhost:3001/api/chat \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"Say hi in 5 words."}]}'
   ```
   Expect `{"message": "...", "provider": "ollama"}` — same behavior as
   Stage 2/3, provider defaults to `ollama` when omitted.
4. **Cloud provider via curl, same server, no restart, explicit model**
   ```bash
   curl -s -X POST http://localhost:3001/api/chat \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"Say hi in 5 words."}],"provider":"cloud","model":"liquid/lfm-2.5-2.6b:free"}'
   ```
   Expect `{"message": "...", "provider": "cloud"}`. Omit `model` to use the
   server's `OPENROUTER_MODEL` default instead.
5. **Grounded RAG chat works with both providers**
   ```bash
   curl -s -X POST http://localhost:3001/api/chat/rag \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"Does the Fleet Visibility package include alerting?"}],"provider":"cloud"}'
   ```
   Expect citations to still appear — retrieval is unaffected by provider
   choice; repeat with `"provider":"ollama"` and compare.
6. **Missing/invalid cloud API key fails clearly**
   Temporarily blank out `OPENROUTER_API_KEY` in `.env`, restart the API, and
   send a `provider: "cloud"` request — confirm a clear `5xx`/error message
   rather than a hang or silent crash. Restore the key afterwards.
7. **Rate-limited/unavailable free model fails clearly, not silently**
   Pick a free model from step 2 that OpenRouter is currently rate-limiting
   (this happens often on the shared free pool) and confirm the API returns
   a `5xx` with a specific, actionable error message (naming the model and
   suggesting a different one) rather than a generic
   "I could not generate a response."

## Developer note

Files/modules added or changed for this increment:

- `apps/api/src/llm/provider.ts` — `generate(systemPrompt, messages,
  provider?, model?)`; per-request provider (and, for cloud, model)
  selection with env-var fallback.
- `apps/api/src/llm/types.ts` — shared `ChatMessage` type.
- `apps/api/src/llm/ollama.ts` — existing Ollama call, extracted unchanged.
- `apps/api/src/llm/cloud.ts` — OpenRouter client (OpenAI-compatible
  request/response mapping); accepts a per-request model override, falls
  back to the default free model slug; detects OpenRouter's embedded
  `error` responses (HTTP 200 with an error body) and empty completions so
  failures surface as real errors instead of a generic fallback message.
- `apps/api/src/routes/llm.ts` — new `GET /api/llm/models`, proxies
  OpenRouter's public model catalog, filtered into `free` (all `:free`
  models) and `paid` (a couple of disabled reference examples); cached for
  5 minutes.
- `.env.example` — documents `LLM_PROVIDER`, `OLLAMA_URL`/`OLLAMA_MODEL`,
  `OPENROUTER_API_KEY`/`OPENROUTER_MODEL`, and how to refresh the free-model
  list.
- `apps/api/src/routes/chat.ts` — both routes accept optional `provider` and
  `model` fields, validate them via `resolveProvider()`/`resolveModel()`,
  and echo the resolved provider back in the response.
- `apps/web/src/main.tsx` / `styles.css` — "Model" `<select>` UI control,
  per-message provider tag, and (when "Cloud" is selected) a second
  "OpenRouter model" dropdown fetched from `/api/llm/models`, with paid
  examples rendered disabled/greyed out.
