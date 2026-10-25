# Project history reference (for picking up in a fresh session)

This is a **background-reference** summary, not a live doc to maintain. It
exists so that a brand-new chat session (one that doesn't have this
project's full conversation history loaded) can quickly get oriented by
reading this file, without needing to replay three old sessions. The
authoritative "current state" docs are still `tech-stack.md`,
`architecture.md`, and `api-reference.md` — this file is the *narrative*
of how we got here and what's still open.

Sourced from three sessions:
1. **customer-compass (old repo, pre-rename)** — session `89041447`, Sep 7:
   continuing Stage 3 (Basic RAG) into PR #2.
2. **customer-compass (old repo)** — session `0b450fc8`, Sep 21: a
   code-walkthrough explainer of the Stage-3 RAG request flow (educational,
   no code changes) — superseded once the stack migrated to FastAPI/Qdrant.
3. **customer-compass-v2 (current repo)** — session `eafa2a5f`, Sep 7 → Oct
   16: the long-running main thread. Everything below that isn't from the
   two old sessions comes from here.

## How the project started

- Began as **"Customer Compass"**: a synthetic-data CRM + RAG learning
  project, hand-rolled on purpose (not framework-first) to actually learn
  the mechanics of RAG/LLM-app-building rather than lean on LangChain/etc.
  from day one.
- Originally: Node/Express API (`apps/api`), Postgres **with pgvector**
  for both relational CRM data and embeddings (pgvector is a Postgres vector-search extension, unused in v2), Ollama for local LLM +
  embeddings, React frontend (`apps/web`).
- GitHub account for this repo: **`dsailajakrishna0-ship-it`** (not the
  default `devarapalli-ojas` account active in this environment — `gh`
  silently defaults to the wrong account sometimes; always confirm with
  `gh auth switch --hostname github.com --user dsailajakrishna0-ship-it`
  before `gh pr create` if PR creation fails with a "must be a
  collaborator" error).

## Stage-by-stage history (condensed)

| Stage | What it added | Status |
| --- | --- | --- |
| 1-2 | Foundations: seeded CRM schema (companies/contacts/deals/interactions), basic `/api/chat` general-chat endpoint | done, old repo |
| 3 | Basic RAG: pgvector-backed ingest/retrieve pipeline, 8 synthetic docs, `/api/chat/rag`, citations in UI | done, old repo, PR #2 |
| 4 (v1 numbering) | Realistic CRM RAG: DB-facts vs RAG-vs-both question routing, company-scoped retrieval. **Renumbered:** in the current Part-based docs this is Stage 5; Stage 4 is now the cloud LLM provider (OpenRouter) | done |
| **Migration** | Full **v2 rewrite**: repo renamed `customer-compass` → `customer-compass-v2`, backend rewritten **Express → FastAPI/Python** (`apps/api-py`), vector store moved **pgvector → Qdrant** and embeddings moved **Ollama `mxbai-embed-large` → Google `gemini-embedding-001`** (Postgres's `vector(1024)` column still exists in `db/002-rag.sql` but is now dead/unused legacy schema), added **cloud LLM provider (OpenRouter)** alongside local Ollama, frontend refactored into proper layers (types/api/hooks/context/components/pages+routing — see `web-refactor-01..04` todos, all done) | done |
| 6 | Retrieval evaluation (promptfoo eval suite (a harness that sends test questions to the live API and grades the answers — `evals/README.md`, `docs/part-2.../06-retrieval-evaluation.md`) | done, PR #6 |
| 6.1 | Bug-fix follow-up: response-truncation fix (`MAX_RESPONSE_TOKENS=700`), model-dropdown-closes-unexpectedly fix (`ModelPicker.tsx`), error-field contract mismatch fix (`error`/`detail` dual-key) | done, PR #7, merged |
| 7 | **Production concerns**: automatic one-shot cross-provider LLM fallback (cloud↔ollama) + full per-request telemetry (tokens/latency/provider-model/estimated cost) shown in logs + UI usage footer. Scope was explicitly discussed/narrowed via `ask_user` — the original Stage 7 placeholder (auth, audit logging, rate limiting) was deferred, not built; see "Deferred" section in `docs/part-3-trust-safety/07-production-concerns.md` | **PR #8, merged** |
| 8 | **Prompt-injection guardrails**: rule-based scan of user messages and retrieved chunks (neutralize-in-place), `<untrusted_context>` delimiting, `guardrail` field on every chat response — see `docs/part-3-trust-safety/08-prompt-injection-guardrails.md` | PR #9, merged |
| — | Expanded sample data to 7 companies / 16 documents | PR #10, merged |
| 9 | **Tool calling via MCP**: stdio MCP server with 4 tools, hand-rolled fenced `tool_call` protocol, text-based confirmation gate for the mutating tool, `tasks` + `tool_audit_log` tables, `/api/v1/chat/tools` — see `docs/part-4-autonomy-protocols/09-tool-calling-mcp.md` | PR #11, merged |
| — | v3 roadmap draft (`docs/v3-roadmap-draft.md`); stage-by-stage capability table in `architecture.md` | PR #12 merged; PR #13 open |
| 10 | Agentic CRM assistant | **planned, not started** |

## Learning-plan / curriculum discussions (not yet scheduled into stages)

The user is deliberately building this project stage-by-stage as a
hands-on Gen AI/agentic-AI curriculum. A topic list was discussed and
explicitly **not yet planned into stages** — just kept as a backlog for
when ready:

1. Gen AI fundamentals (tokens, context windows, prompting, temperature,
   hallucinations, model limitations) — **mostly already touched via
   hands-on building**, not a dedicated stage.
2. LLMs and model serving (transformers conceptually, quantization,
   Ollama, local vs. hosted) — **partially covered** (Ollama is already in
   use; quantization/transformers internals not yet explicitly taught).
3. RAG (embeddings, vector DBs, retrieval, reranking, evaluation) —
   **covered** through Stages 3-6 (reranking specifically not yet added).
4. AI agents (tool/function calling, structured outputs, state, memory) —
   **tool/function calling covered** by Stage 9 (MCP); state/memory and
   structured outputs beyond that not yet explored.
5. Agentic AI (planning, feedback loops, workflow orchestration,
   multi-agent systems, human approval) — **not yet started** (Stage 10 is
   the planned entry point; human-approval is already partly covered by
   Stage 9's confirmation gate).
6. Beyond the basics (fine-tuning, multimodal, MCP, guardrails, AI evals,
   observability) — **MCP (Stage 9), guardrails (Stage 8) and AI evals
   (Stage 6) covered**; fine-tuning, multimodal and observability not yet
   started.

**Where LangChain/framework tooling fits**: discussed explicitly — the
hand-rolled approach is intentional for learning the mechanics first.
LangChain (and friends) are **not a replacement path**, they're a
**comparison/side-exercise path** — see the two open todos
`langchain-isolated-exercise` and `framework-side-exercises` for the
specific hand-rolled-piece → framework-equivalent mapping already sketched
out (retrieval → LangChain VectorStore/Retriever, routing →
LangGraph, prompt templates → LangChain PromptTemplate, provider-swap →
LangChain ChatModel interface, future MCP/agent stages → LangChain
tool-calling / LangGraph agents). These are intentionally **not urgent**
and kept isolated from the main stage sequence.

## Open todos carried forward (not yet started)

- `add-new-company-ui` — no UI/endpoint yet to create a company/contact/deal
  from the browser (currently seed-only).
- `framework-side-exercises` — side-exercise plan above, not started.
- `langchain-isolated-exercise` — narrower version of the same idea, not
  started; reconcile scope with `framework-side-exercises` when picked up.

## Session mechanics learned (worth re-knowing in a fresh session)

- **Two `gh` accounts exist** in this environment; always verify/switch to
  `dsailajakrishna0-ship-it` before any `gh pr create` on this repo.
- The `Authorization` header line in `apps/api-py/app/llm/cloud.py` is
  redacted at the tool layer (shows as `******` even via `cat`) — never
  include that exact line in an `edit` tool's `old_str`/`new_str`; split
  edits around it instead.
- Docker networking: from the **host**, Ollama/Qdrant are at
  `localhost:11435` / `localhost:6333`; from **inside** `api-py`'s
  container, they're `http://ollama:11434` / `http://qdrant:6333` via
  compose DNS. Mixing these up is the most common "why can't it connect"
  bug.
- Don't start a redundant `npm run dev` — check `ps aux` (tty `pts/1`
  = the user's own terminal, tty `?` = an agent-started background
  process) before assuming port 5173 is free.

## Where to actually resume

1. Check `gh pr list` — PR #13 (docs) may still be open; everything through
   Stage 9 is merged to `main`.
2. Pull `main`. The next stage is **Stage 10 (agentic assistant)**, or the
   v3 direction in `docs/v3-roadmap-draft.md`.
3. Read `docs/tech-stack.md` and `docs/architecture.md` first for the
   authoritative current state.
