# 0018 — The agent as a LangGraph graph, and how a paused run resumes

- **Status:** Accepted
- **Date:** 2026-11-05
- **Roadmap sub-stage:** 3.2 (split into 3.2a and 3.2b)

## Context

3.2 rebuilds the account follow-up agent as a LangGraph graph with a human-approval pause (`interrupt()`) before the write, saved in Postgres so a paused run survives an API restart. The exit criterion is that the 26 contract tests pass unchanged ([ADR 0017](0017-contract-and-internal-tests.md)).

The obvious way to resume a paused run is to return a run id from `/agent/recommend` and take it back in `/agent/confirm`. The contract forbids both: the `/recommend` response must have exactly the documented keys, and `/confirm` takes only `companyName`, `note` and `confirm` and is tested as a plain "write a task" endpoint with no earlier run.

## Decision

1. **Split in two PRs.** 3.2a is the graph with identical behaviour. 3.2b adds the Postgres checkpointer, `interrupt()`, a `write` node and the resume path. Each is small enough to review and try on its own.
2. **Nodes:** `classify`, `evidence`, `documents`, `analyze`, `review` (with `prepare_revision` for the one loop), `draft`, `human_approval` (and `write` in 3.2b). The node functions are the old workflow's steps moved, not rewritten.
3. **State is plain data** (dicts, lists, strings), so a checkpointer can save it. Things that cannot be saved or must survive an exception (the model call, the limits, the step budget, the trace) live in a per-run `RunContext` passed through the run config. A test keeps the state JSON-clean.
4. **Limits stay in code:** the step budget and timeout wrap the run as before; LangGraph's `recursion_limit` is a backstop only.
5. **Resume without changing the contract (3.2b).** The run's thread id is derived from the company name and the proposed note, so nothing new appears in the response. `/confirm` derives the same id, looks for a paused run and resumes it (the `write` node creates the task); if there is none (a restart without a saved run, or an edited note) it writes directly, exactly as today. The failure mode is today's behaviour.
6. **Checkpoint tables** are created by the library (`setup()`) at startup, over the `psycopg` driver the project already uses.

## Amendment (3.2b): the pause lives in a second small graph

A LangGraph run needs its thread id **before** it starts, but the id is derived from the drafted note, which exists only after the agent has run. So the agent is two graphs: part 1 (`build_graph()`, classify to draft) runs with no checkpointer, and part 2 (`build_approval_graph()`, `human_approval` then `write`) starts from part 1's finished state under the derived thread id, stops at `interrupt()` and is saved in Postgres. `/agent/confirm` derives the same id and resumes part 2 with `Command(resume={"confirm": ...})`. Nothing is saved while the agent is still thinking; only a run that reached the gate is worth keeping. The thread id is a SHA-256 of the lower-cased company name and the note, so case and spaces in the company name do not matter. The `/agent/confirm` fallback is unchanged: no paused run, direct write (or decline).

## Alternatives considered

- **Return a run id and require it in `/confirm`.** Cleaner, but it deliberately changes the contract, which the port is meant to prove it does not. Left as a later, explicit contract change if the derived id proves awkward.
- **One PR for the whole of 3.2.** Fewer PRs, but a graph rewrite and a persistence change in one diff is harder to review and harder to roll back.
- **A custom `agent_runs` table to find paused runs.** Works, but a second source of truth next to the checkpointer.

## Consequences

- Two runs of the same company that propose the same note share a thread id; the later run replaces the earlier paused one. This is intended.
- If the user edits the note before confirming, the paused run is not found and the direct write is used. The task is still created, but the paused run stays unused.
- A new dependency tree (`langgraph`, `langchain-core` and others) enters the API image; 3.2b adds `langgraph-checkpoint-postgres` and `psycopg-pool`.
- (3.2b) Running the same company with the same note again adds checkpoint rows to the same thread, and finished runs are not deleted. The tables grow slowly with use; a clean-up job is left for a later stage (Stage 7, operations) and is not needed for the demo.
