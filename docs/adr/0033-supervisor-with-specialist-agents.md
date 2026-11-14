# 0033: a supervisor with specialist agents

- **Status:** Accepted
- **Date:** 2026-11-14
- **Roadmap sub-stage:** E3.1 (Python extension; the twin of the Java edition's E3, its ADR 0020)

## Context

The account follow-up agent (Stage 10, [ADR 0018](0018-langgraph-graph-and-resume.md)) is a fixed pipeline: classify, gather evidence, analyse, review, draft. Code decides the order and every model does one job. The Java edition built a **supervisor with specialist agents** as its next agent concept: a coordinator that decides, turn by turn, which specialist works next and takes control back after each one. The Python edition builds the same thing so the two editions stay level, and so the notes can show what each stack makes easy.

The shared API contract does not change. `POST /api/v1/agent/supervise` is a Python (and Java) extension route, listed in [`python-extensions.md`](../python-extensions.md).

## Decision

`POST /api/v1/agent/supervise` takes the request of `/agent/recommend` (`message` 1 to 1000 characters, optional `model`) and returns its shape plus a `supervisor` object: every decision (`turn`, `next`, `source` = `supervisor` or `code`, `reason`, `allowed`, and `proposed` when the model's answer was overridden), `modelDecisions` and `codeDecisions`. A message that is not a follow-up request gets the same `route: "direct"` answer as `/agent/recommend` (the answer team for plain questions is the next slice, E3.2). A completed run waits at the **same approval gate**: `POST /agent/confirm` resumes it, and nothing is written before the user says yes.

- **One LangGraph graph** (`build_graph()` in `app/agent/supervisor.py`): `START → supervisor`, a conditional edge from the supervisor to each specialist or `END`, and an edge from every specialist back to the supervisor. This is the standard LangGraph supervisor topology. It is compiled once: the run's model call, limits and trace travel in the config, as in the account agent.
- **Five specialists**, four of them the account agent's nodes unchanged (same prompts, parsers, the reviewer's two code rules, the guard, the audit log): `crm_facts` (identify the customer, load facts, deals and interactions), `analyst`, `reviewer`, `drafter`; and a new `researcher` that searches every knowledge base ([E1](0029-knowledge-bases.md), `search_all`) and adds the chunks to the evidence, scanned and neutralised like any stored text.
- **The supervisor is a model, so its choices are enforced in code.** Each turn code computes the list of **allowed** specialists from preconditions: nothing before `crm_facts`; no customer found means `FINISH`; with no recommendation the `analyst` and the `researcher` (at most twice); a recommendation not yet reviewed means the `reviewer`; a review that approved, or one with no revisions left, means the `drafter`; a "revise" with revisions left means the `analyst` again (or the `researcher`); a written note means `FINISH`. The first entry is the next step the fixed pipeline would take. The model's answer is accepted only if it is in the allowed list; an unreadable or disallowed answer is replaced by that first entry and the turn is recorded as made by `code`, with the reason and what the model proposed.
- **No model call when there is no choice.** If exactly one specialist is allowed (most turns) the supervisor is not asked. The genuine choices are narrow: whether to call the researcher before the analyst, and, after a "revise", whether to research again.
- **A review belongs to one recommendation.** `rec_version` counts the analyst's proposals and `review_version` records which one the stored review is of, so a review of an earlier recommendation never lets the drafter run.
- **Limits live in code:** `SUPERVISOR_MAX_TURNS` (default 10: how often the supervisor may decide), the existing `AGENT_TIMEOUT_SECONDS`, the existing revision limit, and a research cap of two. The specialists' own steps are budgeted at four per allowed turn (`RunBudget`). A run that hits a limit ends as `budget_exceeded` or `timed_out` with its trace.
- **No customer found ends the run at once**, with no model call.
- **The supervisor's prompt is data in, JSON out:** the request, a short state summary and the allowed list; it answers `{"next": "<name>", "reason": "<one sentence>"}`.

## Differences from the Java edition

- The two editions share the rules, the response shape and the settings name (`SUPERVISOR_MAX_TURNS` here, `supervisor.max-turns` there). The graph engine differs (LangGraph here, LangGraph4j there), as for the account agent.
- The run's context (model call, limits, trace) lives in the LangGraph config; the Java edition compiles the graph per run and closes over it.
- This slice has no answer team and no supervisor-written search words: the Java edition's E3.2 adds them, and E3.2 here will too.

## Alternatives considered

- **Specialists as tools of one tool-calling model:** fewer moving parts, but the supervisor's decisions vanish into tool calls, the preconditions would have to be enforced inside every tool, and a small model calls tools unreliably (Stage 5.5, [ADR 0028](0028-agent-manual-or-prebuilt.md)).
- **LangGraph's prebuilt supervisor helper:** hides the allowed lists and the decision record that are the point of the slice.
- **Letting the model's choice stand without allowed lists:** simplest to build, and a small model skips the reviewer or finishes early. The rules are the safety.

## Consequences

- With the allowed lists the supervisor can only reorder two optional steps. That is deliberate for a first slice: autonomy within guardrails.
- A run costs the pipeline's model calls plus one supervisor call per genuine choice (`modelDecisions`).
- Every decision is in the response, so a reader can see why the researcher ran, why the supervisor's answer was overridden, or why a run stopped.
- Not measured yet: how the supervisor compares with the pipeline on cost and outcome. That is E3.3, on the same ten golden cases as the Java edition.
