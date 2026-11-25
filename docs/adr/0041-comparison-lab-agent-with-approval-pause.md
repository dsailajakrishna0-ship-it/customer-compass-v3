# 0041 — Comparison lab, the agent with an approval pause: a LangGraph graph against LangChain's `create_agent`

- **Status:** Accepted (E5.5; measured with a scripted model, no live model run)
- **Date:** 2026-11-27
- **Roadmap sub-stage:** E5.5 (the Python twin of the Java edition's J8.5; plan in [the E5 guide](../stages/E5-comparison-lab.md))

## Context

A short 🟪agent run: look a company up, ask the model for **one** recommended next action, **pause until a person approves**, then perform the action as a **dry run** (nothing is written anywhere). The application keeps its pause in Postgres (ADR 0018); the lab keeps it in memory and compares how the two 🟦frameworks express the same run: 🟦LangGraph as a graph we draw, 🟦LangChain as one `create_agent` call with human-approval middleware.

## Decision

1. **The same face as Java's agent backends:** `POST /api/v1/agent/start` (`company` of at most 200 characters, optional `model`), `POST /api/v1/agent/resume` (`runId`, `approve` true or false) and `GET /health`; the answer has `runId`, `status` (`awaiting_approval`, `completed`, `declined`), the four `steps` (`gather`, `recommend`, `approval`, `act`) with their status, the `recommendation` (`action`, `rationale`) and a `message`. 404 for an unknown company or run, 409 for a run that was already answered, 422 for a bad request, 503 (by kind of failure, never a library's text) when the CRM or the model is missing. Only the most recent 100 runs are kept; an evicted run is unknown.
2. **withLangGraph, port 19141:** a `StateGraph` with the nodes `gather`, `recommend`, `approval` and `act`; code decides the order, the model is called once (by `recommend`). The pause is **`interrupt()` inside the approval node**, the state is kept by `InMemorySaver` per thread id (the run id), and a run is resumed with `Command(resume=approve)`.
3. **withLangChain, port 19142:** `create_agent(model, tools, middleware=[HumanInTheLoopMiddleware(interrupt_on={"create_followup_task": True})], checkpointer=InMemorySaver())` with two tools, `get_company_summary` and `create_followup_task` (the dry run). **The model decides the steps:** it looks the company up, then calls `create_followup_task` with the action it recommends; the recommendation is the arguments of the paused call. A run is resumed with `Command(resume={"decisions": [{"type": "approve"}]})`.
4. **Declining ends the run in our code** in withLangChain (the run is marked declined and its saved state deleted), because the framework's own `reject` decision hands the rejection back to the model (measured below).

## What each did (measured in `comparisons/tests/test_agent_graph.py`)

| Point | withLangGraph | withLangChain |
| --- | --- | --- |
| Who decides the steps | our graph: the order is fixed | the model: if it never calls the tools the run never pauses and the answer is "did not reach the approval step" |
| Model calls for one approved run | **1** (a decline costs the same; `gather` and `act` need no model) | **3**: look up, recommend (the paused call), and a last message after the tool ran |
| The pause | `interrupt()`; **the approval node runs again from its first line on resume** (twice in all), so nothing before the call may have a side effect | the middleware pauses **before** the gated tool runs; the tool ran only after the approval (measured) |
| The recommendation | a field of the state, from the one model call (the shared prompt and parser, a JSON object of at most 200 and 400 characters) | the arguments of the paused tool call; the length rules are checked by us after the pause |
| The framework's decline | the conditional edge goes to the end: no more model calls | `reject` **hands the rejection to the model, which makes one more model call and could ask for the tool again** (measured: 3 calls, and the tool did not run); so a decline is ended by our code |
| Unknown company | our `gather` node reads the tool's answer and raises | the model gets a "not found" tool result; found afterwards in the tool messages |
| Saved state | `InMemorySaver` keeps a finished run until it is deleted (measured); our bounded store deletes the thread of an evicted run | the same |
| Errors in nodes and tools | an exception raised in a node reaches the caller unchanged (so the 404 and 503 mapping needed no unwrapping, unlike the Java LangGraph4j agent) | the model call failure is caught and reported by kind |

**Size** (non-blank, non-comment lines, docstrings included): the LangGraph approach 104, the LangChain approach 160; shared: the face and the run store `agent.py` 167, the recommender `recommender.py` 75.

**What stayed ours in both:** the face and its validation, the four-step view, the 100-run bound, the dry-run message, the decline message and the safe error messages.

## How this was run

`just comparisons-test` (162 tests, no key, no network, in CI; the agent tests were also run 30 times in a row without a failure). Both backends were also started once through `just` with a fake key and unreachable addresses: `GET /health` answers, a start gets a 503 that names the kind of failure (`The CRM could not be reached.` for withLangGraph, whose first step is the CRM; `The model call failed (OpenAIConnectionError).` for withLangChain, whose first step is the model), an unknown run id is a 404, a malformed one a 422, and the fake key is in no log line.

**Not measured:** a real model. In particular, **whether a real model reliably calls `get_company_summary` and then `create_followup_task`** (the risk of the model-decided version) and how good its recommendations are; speed and cost. Also not built: durability (the Python application keeps its pause in Postgres; here the pause is lost on a restart).
