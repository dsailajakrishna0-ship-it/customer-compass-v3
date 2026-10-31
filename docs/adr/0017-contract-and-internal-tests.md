# 0017 — API-contract tests and internal tests

- **Status:** Accepted
- **Date:** 2026-10-31
- **Roadmap sub-stage:** 3.1

## Context

Stage 3.2 replaces the hand-written agent workflow with a LangGraph graph. The exit criterion is "contract tests pass unchanged". That sentence means nothing until it is clear which tests are *the contract*. The existing agent tests were a mix: some drove the API, but most called workflow functions directly and replaced about 27 internals, so a rewrite would have broken them for reasons that say nothing about behaviour.

## Decision

1. **Three kinds of test, documented in `apps/api-py/tests/README.md`:**
   - **API contract** (`tests/contract/`): drives `POST /api/v1/agent/recommend` and `/agent/confirm` over HTTP against the real app and the real Postgres demo data, and asserts only what a caller can see. *Must pass unchanged through 3.2.*
   - **Agent internals** (`tests/agent_internals/`): the four existing files that test the current workflow, agents, policies and route functions. *Allowed to change or be replaced in 3.2.*
   - **Everything else**: gateway, settings, MCP, guardrails, ingestion, migrations, repository rules. Not about the agent's structure.
2. **Two seams, and only two.** A contract test cannot use the internet or a model, so it replaces the model (`app.routes.agent.make_llm`, which the route now exposes as a named function) and document retrieval (`app.mcp.tools.retrieve_relevant_chunks`). Everything else is real, including the database, the guardrails, the limits (set through the `AGENT_*` variables) and the trace. **The port must keep both seams**, or move them and update the README and `conftest.py` in the same change.
3. **The boundary is enforced, not hoped for.** `tests/test_contract_boundary.py` fails if a contract test imports application code, patches anything, names a seam outside `conftest.py`, if the seams in `conftest.py` differ from the table in the README, if a documented seam no longer exists, or if a test file is not classified in the README.
4. **The contract includes failure.** Writing the contract found that a real analysis with no model or no embeddings key returned an opaque `500`. It is now a `503` with the reason (`LlmUnavailableError` and a new `EmbeddingsUnavailableError`), pinned by contract tests, and the web app shows the text.
5. **Run separately and visibly:** `just test-contract`, `just test-internal`, and a separate CI step for the contract tests.

## Alternatives considered

- **Tag instead of move:** a marker on the four internal files would do, but a folder makes the boundary visible when browsing; the `contract` marker exists too (`pytest -m contract`).
- **Contract tests against a live stack with a real model:** the most honest check, but slow, flaky on free models and impossible in CI without a key. The seams make the contract deterministic; real-model behaviour stays the job of the evaluation suite.
- **Patch the database too:** would make the tests independent of demo data, but hides schema and SQL regressions, and the demo data is part of the repository.

## Consequences

- **The contract is only as wide as its 26 cases.** It covers recommend and confirm; it does not cover `/chat/*` (not part of the port) or what a *real* model does with the prompts.
- **The model's JSON reply format is part of the seam** (`action`, `rationale`, `evidence`; `verdict`, `reasons`; `task_note`). If the graph port changes what it asks the model to return, the fake must change, and the README says so.
- **The contract tests need Postgres with the demo data**, like most of the suite (`just test-contract` starts and migrates it).
- A contract test that cannot be written without reaching into internals is a sign the API lacks a behaviour worth defining, not a reason to loosen the rule.
