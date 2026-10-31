# How the API tests are organised

The test suite has three kinds of tests. The difference matters in Stage 3.2, when the hand-written agent
workflow is replaced by a LangGraph graph: **the contract tests must pass unchanged, the internal tests are
allowed to change.**

| Kind | Where | What it checks | May it change in 3.2? |
| --- | --- | --- | --- |
| **API contract** | `tests/contract/` | What a caller of `POST /api/v1/agent/recommend` and `/agent/confirm` can see: statuses, response and trace shape, limits, "recommending never writes". Driven over HTTP against the real app and the real Postgres demo data. | **No.** If one fails after the port, the port changed behaviour. |
| **Agent internals** | `tests/agent_internals/` | How the current workflow works inside: its functions, its helpers, its policies. | **Yes.** These test the old structure and are rewritten with it. |
| **Everything else** | `tests/test_*.py` | The gateway, settings, tools and MCP, guardrails, ingestion, migrations, repository rules. Not about the agent's structure. | Not by the port. |

Run them separately:

```bash
just test-contract    # only the contract tests   (pytest -m contract)
just test-internal    # everything except them    (pytest -m "not contract")
just test-api         # all of it, with coverage (what CI runs first)
```

## The two seams

A contract test must not need the internet or a model, so it replaces exactly two things, and **only
`tests/contract/conftest.py` may name them**:

| Seam | What it stands for | Replaced by |
| --- | --- | --- |
| `app.routes.agent.make_llm` | The model: `llm(role, system_prompt, messages) -> GenerationResult`, called with the role `analyst`, `reviewer` or `task_drafter`. The agents expect JSON replies (`action`, `rationale`, `evidence`; `verdict`, `reasons`; `task_note`). | A scripted fake that answers by role; it may raise `LlmUnavailableError` (no model) |
| `app.mcp.tools.retrieve_relevant_chunks` | Document retrieval (embeddings and the vector store) | A few canned chunks; it may raise `EmbeddingsUnavailableError` (no embeddings key) |

Both seams may fail with their public error type, and the API must then answer `503` with that error's message (nothing is written).

Everything else is real: the FastAPI app, the database (demo data from migration 0002), the guardrails, the
limits (set through the `AGENT_*` environment variables), the tool code. **The port must keep both seams**
(or move them and update this table and `conftest.py` in the same change).

## Rules for a contract test

- Drive the API over HTTP (the `api` fixture). Do not import from `app.agent` or `app.routes`, and do not
  patch anything; use the `use_model` fixture for the model.
- Assert only what a caller can see. Do not assert on prompt wording or internal function calls.
- Clean up what you write (the `clean_test_tasks` fixture removes tasks whose note starts with `CONTRACT-TEST`).

`tests/test_contract_boundary.py` enforces these rules, and that every test file is listed below.

## Every test file, by kind

| File | Kind | Area |
| --- | --- | --- |
| `contract` | contract | Agent API: recommend, confirm |
| `agent_internals` | internal (agent) | Workflow, agents, policies, route functions |
| `test_chat_router.py` | other | Chat |
| `test_chat_tools.py` | other | Chat and tools |
| `test_tool_schemas.py` | other | Chat and tools |
| `test_mcp_contract.py` | other | Chat and tools |
| `test_mcp_http.py` | other | Chat and tools |
| `test_mcp_registry.py` | other | Chat and tools |
| `test_mcp_tools.py` | other | Chat and tools |
| `test_documents_search.py` | other | Chat and tools |
| `test_gateway.py` | other | Model gateway and settings |
| `test_config.py` | other | Model gateway and settings |
| `test_logging.py` | other | Model gateway and settings |
| `test_llm_models_route.py` | other | Model gateway and settings |
| `test_no_local_models.py` | other | Model gateway and settings |
| `test_adversarial_set.py` | other | Guardrails |
| `test_llm_guard.py` | other | Guardrails |
| `test_output_guard.py` | other | Guardrails |
| `test_prompt_guard.py` | other | Guardrails |
| `test_security_audit.py` | other | Guardrails |
| `test_chunking.py` | other | Retrieval and ingestion |
| `test_ingest.py` | other | Retrieval and ingestion |
| `test_ingest_route.py` | other | Retrieval and ingestion |
| `test_search_strategy.py` | other | Retrieval and ingestion |
| `test_migrations.py` | other | Database |
| `test_health.py` | other | Database |
| `test_ai_terms.py` | other | Repository rules and tooling |
| `test_eval_baseline.py` | other | Repository rules and tooling |
| `test_measure_limits.py` | other | Repository rules and tooling |
| `test_network_guard.py` | other | Repository rules and tooling |
| `test_test_hygiene.py` | other | Repository rules and tooling |
| `test_resolve_conflicts.py` | other | Repository rules and tooling |
| `test_contract_boundary.py` | other | Repository rules and tooling |
