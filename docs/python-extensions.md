# Python extensions

From 2026-11-13 the Java and Python editions grow **separately**, so the notes show what each stack teaches. The Java edition lists its own additions in [`java-extensions.md`](https://github.com/dsailajakrishna0-ship-it/customer-compass-v3-java/blob/main/docs/java-extensions.md). Everything on this page exists only in the Python edition.

**The shared API contract does not change.** Extensions are new routes, new settings and new code, never a change to a route or tool the Java edition has. The contract suite (`just test-contract`) and the 🟦MCP tool list (`contracts/mcp-tools.json`) keep passing unchanged, and the extra routes are documented here and in their stage guides, not in the shared [API reference](api-reference.md).

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](ai-terms.md)

## E1: multi-source RAG with routing

Several 🟪knowledge bases (the CRM documents and, for example, a farm-supply handbook) and a model that searches across them. Different from multimodal 🟪RAG (one index holding many kinds of content). The Java edition did this first (its ADRs 0017 to 0019); the Python edition does the same three slices with its own idioms.

| Slice | What | Status |
| --- | --- | --- |
| E1.1 | A knowledge-base registry, a second corpus in its own collection, `GET /knowledge-bases`, `POST /knowledge-bases/{id}/ingest`, `POST /knowledge-bases/{id}/search`. [ADR 0029](adr/0029-knowledge-bases.md), [guide](stages/E1-multi-source-rag.md) | Merged |
| E1.2 | Three ways to decide where to search (a router, search everything and merge, an 🟪agent with a tool), on one route, `POST /chat/multi`, as one 🟦LangGraph graph. [ADR 0030](adr/0030-multi-source-strategies-as-a-graph.md) | In review |
| E1.3 | A replayable comparison of the three on the same 24 labelled questions as the Java edition, replayable without keys (`just eval-multi`, checked in CI). [ADR 0032](adr/0032-multi-source-strategy-results.md) | In review |

## E3: a supervisor with specialist agents

A coordinator model that decides, turn by turn, which specialist works next, with the rules in code (the twin of the Java edition's E3).

| Slice | What | Status |
| --- | --- | --- |
| E3.1 | `POST /agent/supervise`: a supervisor and five specialists (CRM facts, researcher, analyst, reviewer, drafter) as one 🟦LangGraph graph, the allowed lists in code, the decisions in the response, the same approval gate. [ADR 0033](adr/0033-supervisor-with-specialist-agents.md), [guide](stages/E3-supervisor.md) | In review |
| E3.2 | An answer team for plain questions (CRM facts, researcher, answerer; a grounded answer or a fixed "not found" text, no task, no gate), and the supervisor's own search words. [ADR 0034](adr/0034-answer-team-and-supervisor-queries.md) | In review |
| E3.3 | A replayable comparison with the fixed pipeline on the Java edition's ten golden cases | Planned |

| Route or setting | What it does |
| --- | --- |
| `POST /api/v1/agent/supervise` | The request of `/agent/recommend` (`message`, optional `model`); the response is the recommend shape plus `supervisor` (`turns`, `modelDecisions`, `codeDecisions`). A follow-up request runs the task team; any other message runs the answer team and gets `status: "answered"` with `message`, `grounded` and `citations` (no task). A completed run waits at the same gate: `POST /agent/confirm` |
| `SUPERVISOR_MAX_TURNS` | How often the supervisor may decide who works next (default 10); a run that hits it ends as `budget_exceeded` |

## New routes and settings (E1.1 and E1.2)

| Route or setting | What it does |
| --- | --- |
| `GET /api/v1/knowledge-bases` | The 🟪knowledge bases (`crm` and the extra ones) with description, collection, `builtIn` and 🟪chunk count |
| `POST /api/v1/knowledge-bases/{id}/ingest` | Rebuilds an extra knowledge base from its folder; never touches the CRM documents (`crm` answers 400: use `POST /documents/ingest`); 502 with the summary if the run fails |
| `POST /api/v1/knowledge-bases/{id}/search` | `{"query": "...", "topK": 4}`: the chunks of that knowledge base only, with the 🟪RAG citation shape (`topK` 1 to 20) |
| `KNOWLEDGE_BASES` | A JSON list of `{"id", "label", "description", "source_dir"}`; the default is the farm-supply handbook in `sample-data/knowledge-bases/agri-supply/` |
| `POST /api/v1/chat/multi` | A chat question answered from several knowledge bases. Body: the usual chat body plus `"strategy"`: `route` (default), `all` or `agent` (anything else is a 422). The response adds `routing` (strategy, searched ids, reason, tools used, model calls) and a `knowledgeBase` on each citation |
