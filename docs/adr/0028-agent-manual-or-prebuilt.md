# 0028 — The agent's evidence step: our fixed graph or a LangChain prebuilt agent

- **Status:** Accepted: **manual wins**; the framework side ships as `AGENT_IMPL=frameworks`
- **Date:** 2026-11-13
- **Roadmap sub-stage:** 5.5 (seam 3 of 3)

## Context

[ADR 0018](0018-langgraph-graph-and-resume.md) settled that LangGraph runs the agent, with the order of steps decided by code: find the company, read the CRM facts, the recent interactions and the documents, one Analyst call, a Reviewer with two code rules, a Task Drafter, an output guard, then the confirm gate. The roadmap left one question open: would a **prebuilt agent**, where the model chooses which tools to call and when to stop, do the evidence-and-analysis part better? (`create_react_agent` in LangGraph is deprecated in favour of `langchain.agents.create_agent` in `langchain` 1.5.0, checked on PyPI on 2026-11-13, so the new one is used.)

## Decision

1. **`AGENT_IMPL=manual|frameworks`, default `manual`.** `run_account_review` keeps its signature and its response. With `frameworks`, one node (`research`) replaces `evidence`, `documents` and `analyze`; the model gets three tools (`get_company_summary`, `get_recent_interactions`, `search_documents`) and a `create_agent` loop picks them.
2. **Everything that makes the agent safe is shared, not re-implemented.** The request guard and company check (`classify`), the evidence labels E1, E2, ... and the scan of stored text, the Reviewer and its two code rules, the revision limit, the Task Drafter, the output guard, **the confirm gate** (the second graph, the thread id, the Postgres pause, `/agent/confirm`), the step budget, the timeout, the trace and the tool audit log. The gateway and the confirm gate stay manual, as the roadmap says.
3. **The model is called through the run's own model seam** (`ctx.llm`, role `analyst`, with an optional `tools` argument), which is the gateway in production and the scripted fake in the contract tests. A small `BaseChatModel` adapter turns LangChain messages into the gateway's. No new model client and no new provider package.
4. **The whole research loop is the Analyst's one step in the step budget**, plus one per tool call, so a normal run costs 6 steps and a revision 2, exactly as in the manual graph and within the default limit of 8. (Counting every model turn as a step made a revision cost 6 and the default budget ran out; the contract suite caught it.) A **revision does not gather evidence again**: the Reviewer's reasons go back to our Analyst call with the evidence already collected, unless nothing was collected.
5. **The request reaches the model only as the guard left it.** My first version put the raw request text in the prompt and the contract test "an injection in the request never reaches the model" failed. The manual agents never show the request to any model, only the labelled evidence.
6. **The same contract tests run against both sides** (`just test-frameworks`, and in CI): all 26 pass with `AGENT_IMPL=frameworks`. The only changes to them are three assertions that list the model's calls (the prebuilt agent asks the model once more, to choose its tools, before the Analyst's answer) and a fake that accepts the new `tools` argument.
7. **Measured on the 10 cases of `evals/golden/agent.json`, twice each**, through `POST /agent/recommend` with one pinned small paid model on both sides (`meta-llama/llama-3.1-8b-instruct`, US$0.02 per million tokens in and 0.04 out, the same pin as ADR 0025). Embeddings for the document search were `BAAI/bge-small-en-v1.5` through FastEmbed (Google's free embedding quota for the day was used up). `just eval-frameworks` replays the recording.

## Results

| | manual | frameworks |
| --- | --- | --- |
| runs with the expected status and company (of 20) | 20 | 19 (one HTTP 503, see below) |
| analyses completed (of 14 expected) | 14 | 13 |
| completed with valid citations (every cited label exists) | 14 of 14 | 8 of 13 |
| completed and approved by the Reviewer | 10 of 14 | 7 of 13 |
| revisions per completed run | 0.43 | 1.00 |
| evidence items per completed run | 7.3 | 3.4 |
| evidence tool and code steps per completed run | 3.0 | 1.5 |
| model calls per completed run | 3.9 | 5.6 |
| tokens per completed run | 2,216 | 2,702 |
| median / p95 ms | 10,227 / 18,175 | 6,602 / 20,470 |
| tasks written by `recommend` (must be 0) | 0 | 0 |
| cost for the 20 runs | US$0.0007 | US$0.0008 |
| lines of code this side adds | 84 | 239 |

What the numbers say:

- **The small model rarely chose to use the tools.** On 12 of the 13 completed framework runs the model's first answer came **before any tool call**, so it cited evidence that did not exist. In 7 of them the Reviewer sent it back and the retry called the tools; in 5 it never called one at all and ended with no evidence and invalid citations. In the manual graph the evidence is always gathered, because code does it. "The model decides" includes "decides not to".
- **The safety net held.** Every framework run with invalid citations was marked not approved by the code rule (the same one both sides share), recommending never wrote a task on either side, and the 26 contract tests pass. The framework side did not become less safe; it became less useful.
- **Lower median latency is not a win.** It is faster because it gathered half the evidence (1.5 steps against 3.0). The p95 is a little worse.
- **It is 2.8 times the code** (239 lines against 84) for the model adapter, the three tool wrappers (each must keep the labels, the scans, the budget and the trace), and the shared-node wiring.
- **One run failed with HTTP 503** (the model chain unavailable, on the first framework run). It did not reproduce in four reruns, and that recording did not keep the error text, which the recorder now does.

## Decision on shipping

**Manual wins, and stays the default.** The framework side is not at least as good on quality (valid citations 8 of 13 against 14 of 14, half the evidence), it is not simpler, and its evidence gathering is not repeatable: the same request takes different steps on different runs. The roadmap's rule is that the default changes only if the framework side keeps its quality, so it does not.

**Caveats, stated plainly.** One 8-billion-parameter model; 40 runs; one prompt version, written once and not tuned (the prompt asks for `get_company_summary` first and the model mostly ignored it). A stronger model, or forcing the first turn to call a tool (`tool_choice` set to required, which `create_agent` does not do for you), could change the result; neither was tried.

**What would make us look again:** (1) a model that calls the tools on its first turn in nearly all runs (the number to watch is "first answer before any tool call", 12 of 13 here); (2) the day the choice becomes genuinely open. For a fixed set of three evidence sources, code is better than a model. For "which of several knowledge bases should I search?" (the multi-source retrieval on the roadmap's later agent work) the model choosing the tool is the point, and this side is already built to be measured again.

## What the framework gave and hid

- **Gave:** the loop (model, tools, model, until no tool call), the tool-call message plumbing, the tool schemas from function signatures, and a recursion backstop.
- **Hid, or needed work to keep:** which turn ends the loop; that every model turn is another model call (5.6 against 3.9 per run); our trace (each tool wrapper records its own step so the response's trace keeps the same step names); our budget (counted in the tools, not in the loop); our message format (an adapter in both directions); and its own churn (`create_react_agent` was already deprecated in the LangGraph version we use).

## Alternatives considered

- **`create_react_agent` from `langgraph.prebuilt`:** deprecated in favour of `create_agent`; measuring the deprecated one would have been measuring something we would have to move off.
- **A structured-output final step** (`response_format=...`) instead of our JSON parser: ties the answer to a provider feature a small model may not support; our parser already falls back safely.
- **LangGraph's Corrective-RAG or supervisor templates:** different shapes of agent; the supervisor belongs to the later agent work.

## Consequences

- `app/frameworks/agent.py`, its tests and the contract suite on the framework side run in CI through `just test-frameworks`.
- `LlmCall` gained an optional `tools` argument (used only by this side); the contract suite's model fake accepts it.
