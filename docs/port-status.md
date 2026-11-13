# Sibling repos and port status

Customer Compass V3 (this repo) has a Java sibling and a planned claims project. This page says what each is and how far the Java edition has caught up. Keep it current whenever a stage merges or the API contract changes.

| Repo | Domain | Languages | State |
| --- | --- | --- | --- |
| [`customer-compass-v3`](https://github.com/dsailajakrishna0-ship-it/customer-compass-v3) (this repo) | CRM | Python and Java; the web app's radio buttons pick the path | Stage 5 of 9 (5.2 in review) |
| [`customer-compass-v3-java`](https://github.com/dsailajakrishna0-ship-it/customer-compass-v3-java) | CRM, same API contract | Java only: Spring Boot, Spring AI | J0 to J4 merged (J5, the agent, in progress) |
| `claims-compass-v1` | Insurance claims management | Java only; a Python version is decided later | **Deferred** until this repo and the Java edition are almost complete |
| `inbox-compass-v1` (name to confirm) | Email: categorize an email and answer from help articles | Python, the same free-tier stack | **Deferred**, same condition. An experiment sandbox for studying model behaviour (structured output, RAG off versus on, prompt changes) |

`claims-compass-v1` keeps the "Compass" family name; the `v1` is the API version (`/api/v1/...`, `contracts/mcp-tools.json` version 1). A breaking change would be `claims-compass-v2`.

## Scope order (decided 2026-11-06)

Only the first two repos are active: `customer-compass-v3` and `customer-compass-v3-java`. `claims-compass-v1` and `inbox-compass-v1` start only when those two are almost complete.

`inbox-compass-v1` uses ideas only. It must not contain any employer's code, data, documents, prompts or category lists: its emails and help articles are synthetic or written from public knowledge.

## The rule

The Java edition follows this repo by about one stage. It ports a stage only after it is merged here, and it never changes the API contract: a contract change is made here first, in its own PR, and recorded below.

## Status

Last updated at Stage 5.2 (in review), 2026-11-13. Java: J0 to J4 merged, J5 in progress.

| Stage here | Merged | Contract changed? | Java stage | Java status |
| --- | --- | --- | --- | --- |
| 0 Foundation | Yes | n/a | J0 | Merged |
| 1 Model layer | Yes | Gateway, usage footer, `/llm/models` | J2 | Merged |
| 2 Tools and MCP | 2.1, 2.2a, 2.2b | `/chat/tools`, `/mcp/servers`, `contracts/mcp-tools.json` | J4 | Merged (tools chat; MCP server inside the API) |
| 3 LangGraph port | 3.1, 3.2a, 3.2b | No: the 26 contract tests are unchanged | J5 | In progress (LangGraph4j) |
| 4 Retrieval upgrade | 4.1a, 4.1b (internal only); 4.2 in review | 4.2 adds optional `page` and `sheet` to `/chat/rag` citations and an ingestion metadata rule (see `api-reference.md`) | J3 | J3 merged (RAG, documents); hybrid search and reranker not yet ported |
| 5.1 Tracing | Yes | No: the contract tests are unchanged; tracing is off by default and adds only optional settings | J5 or later | Planned |
| 5.2 Judged evals | In review | No: evals only, nothing in the API changes. The runner reads the HTTP contract, so it can be pointed at the Java API | J6 or later | Planned |
| 5.3 and later | No | Unknown | J6 to J8 | Planned |

The contract is the 26 tests in `apps/api-py/tests/contract/`, [`api-reference.md`](api-reference.md) and `contracts/mcp-tools.json`.
