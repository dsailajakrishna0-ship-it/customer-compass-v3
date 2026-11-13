# 0030 — Three ways to decide where to search, as one LangGraph graph

- **Status:** Accepted
- **Date:** 2026-11-13
- **Roadmap sub-stage:** E1.2 (Python extension; the second slice of multi-source RAG)

## Context

[ADR 0029](0029-knowledge-bases.md) made the application hold more than one corpus. This slice decides **where to look**. The Java edition built three strategies on one route (its ADR 0018) and measured them (its ADR 0019). The Python edition builds the **same three on the same route shape**, so the two can be compared on the same questions in E1.3, but with its own idioms: the Python agent engine is LangGraph ([ADR 0018](0018-langgraph-graph-and-resume.md)), so the strategies are a graph.

The shared API contract and the MCP tool list do not change. `POST /api/v1/chat/multi` is a Python-only route, documented in [`python-extensions.md`](../python-extensions.md).

## Decision

1. **One route, three strategies.** `POST /api/v1/chat/multi` takes the usual chat body plus `strategy`: `route` (default), `all` or `agent`. An unknown value is FastAPI's own 422: type `literal_error`, loc `["body", "strategy"]`, message `Input should be 'route', 'all' or 'agent'` (a pydantic `Literal`, no hand-written check). The response is `message, citations, routing, usage, guardrail`; each citation is the RAG citation plus `knowledgeBase`; `routing` has `strategy`, `searched`, `reason` (route), `toolsUsed` (agent) and `modelCalls`. The shape is the Java edition's, key for key.
2. **`route`: a router model decides first.** One model call reads each knowledge base's description and answers JSON `{"knowledge_bases": [...], "reason": "..."}`. Invented ids are dropped; a reply that cannot be read, or names only unknown ids, **falls back to searching everything** (a router that fails must not hide a corpus), and the `reason` says so; an explicit empty list means "nowhere": the fixed *I could not find any ingested documents relevant to that question.* answer, with the answering model not called.
3. **`all`: search everything and merge.** Every knowledge base is searched with its own retriever **concurrently** (`asyncio.gather`; each task has its own copy of the context variable that aims the retriever, [ADR 0029](0029-knowledge-bases.md)), so each applies its own similarity floor and hybrid search. Scores from different corpora are not comparable, so the lists are merged by **reciprocal rank fusion** (the `rrf_fuse` of [ADR 0019](0019-hybrid-search-and-reranker.md), positions only), then the optional reranker orders the merged candidates. Without a reranker, fusing two disjoint lists is a round robin by rank: fair, not smart.
4. **`agent`: the model decides while it works.** The model gets `search_knowledge_base(knowledge_base [an enum of the ids], query)` and the descriptions in its prompt, and may search several times in several corpora. Sources are numbered across calls in the order returned (`[3]` in the answer is `citations[2]`). Limits as in the tools chat: four model turns that may ask for tools, four calls from one reply, then one forced plain-text answer (`tool_choice="none"`). The arguments are untrusted input: an unknown knowledge base, a missing argument or an unknown tool comes back to the model as a readable result and is **not** recorded as used.
5. **The guard applies to all three exactly as in the RAG route.** The question is guarded first and from then on a model sees only the cleaned text (the router included); every chunk and every tool result is scanned, redacted and wrapped as untrusted before a model reads it; the answer is scanned last; detections go to the audit log with endpoint `chat/multi`. Retrieval uses the original question (redacting it first would hurt the embedding); the citation shows the original chunk text so the reader sees what was retrieved.
6. **The strategies are one LangGraph graph** (`build_graph()` in `app/routes/multi_chat.py`):

   ```
   guard → [by strategy] → router → [nowhere?] → search → respond          (route)
                         → plan_all ──────────────→ search → respond          (all)
                         → agent_turn ⇄ run_tools → force_final → finish      (agent)
   ```

   A conditional edge picks the strategy, a second one the router's verdict, and the agent's loop is a **visible cycle** (`agent_turn` → `run_tools` → `agent_turn`, with a limit that routes to `force_final`) instead of a `while` inside a function. The nodes are plain async functions over plain-data state, as in the account agent; a test keeps the state JSON-clean and another asserts the shape of the graph (the cycle is there).
7. **The agent's tool loop is hand-written nodes, not LangGraph's prebuilt tool node (or LangChain's `create_agent`).** Decided deliberately, with [what 5.5 measured](0028-agent-manual-or-prebuilt.md): with one small paid model the prebuilt agent answered **before calling any tool** on 12 of its 13 completed runs and cited evidence that did not exist, and needed 239 lines against 84. Here the loop must (a) number sources across calls, (b) scan and wrap every tool result before the model reads it, (c) treat arguments as untrusted and not record bad calls, (d) count model calls, and (e) call the model through the gateway (LiteLLM, the fallback chain) like everything else. A prebuilt node needs LangChain tool objects and message types, so (e) would need the adapter 5.5 wrote, and (a) to (d) would be code around a block that hides the loop. LangGraph is used for what it is good at here: **declaring the shape**.
8. **No change to the shared surface.** No tool is added to the MCP server, no shared route or response changes (the contract suite passes unchanged), and the default behaviour of every existing route is the same.

## Python-specific concepts this slice teaches (for the notes)

- **A graph for a decision, not only for a workflow.** The account agent is a sequence with one loop; here the graph's job is branching: `add_conditional_edges` with a path function that returns a node name, and a path map (the list of possible targets) that LangGraph uses to draw and check the graph.
- **State is a `TypedDict(total=False)`; a node returns only what it changed.** LangGraph merges the returned dict into the state. A node name may not equal a state key (the reason the answering node is `respond` and the state key is `message`).
- **Compile once.** `build_graph()` is `functools.lru_cache`d: the graph has no per-run closure (the model call and the knowledge bases are looked up at call time), so one compiled graph serves every request.
- **The same `ContextVar` isolation pays off twice.** Slice 1 used it to aim the retriever; `asyncio.gather` over the knowledge bases is safe for the same reason, with no lock and no extra argument.
- **FastAPI gives the 422 for free** (`Literal`), where the Java edition hand-wrote the FastAPI-shaped problem.
- **Test seams are module attributes.** The tests patch `generate` at its two import sites and `record_events` in the chat route, and the scripted model answers by role (router, answerer, agent), never by reading words inside a prompt.

## Alternatives considered

- **One function with `if strategy == ...` (the Java shape).** The same behaviour, and fewer concepts to learn, but the routing, the fallback and the loop limit are buried in code; the graph declares them.
- **LangGraph's prebuilt tool node or `create_agent` for the `agent` strategy.** See decision 7.
- **LangChain's routing chains.** Older router and multi-retrieval chains are deprecated in favour of LangGraph, and the [framework policy](../roadmap.md) is to adopt a framework for a piece only when measurements say it helps.
- **Routing by embedding similarity** (compare the question with an embedding of each description): no model call and no JSON to read, but it needs a calibrated threshold per embedding model. A possible later variant.
- **A merge by score.** Cosine scores from two corpora are not on one scale; positions are.

## Consequences

- `route` costs one extra model call per question, `agent` one per turn, `all` none (but a retrieval per corpus); `routing.modelCalls` says how many an answer cost.
- The router sees only the cleaned question and the descriptions, never document text.
- The default strategy is `route` because it is the simplest to explain; E1.3 measures whether it deserves to be.
- Checked live on scratch ports (not in CI): all three strategies answered the same question through the real gateway with `meta-llama/llama-3.1-8b-instruct` and the local FastEmbed model `BAAI/bge-small-en-v1.5` (Google's free embedding quota for `gemini-embedding-001` is spent until about 13:30 IST on 2026-11-14), the 422 and the guard behaved as in the tests, and the CRM document count stayed at 19. That model scores unrelated text around 0.6, so the 0.45 floor means little there and no ranking claim is made from it.

## Plan for E1.3 (not started)

A replayable comparison of the three strategies on **the same 24 labelled questions the Java edition used** (8 CRM, 8 farm-supply, 4 that need both, 4 that belong to neither), with the same metrics (right sources found, knowledge bases searched, citations from the wrong corpus, model calls, latency), recorded once with a pinned small paid model on the default embedding model (`gemini-embedding-001`, after its quota resets), replayed in CI without keys, and set beside the Java table in the stage guide.
