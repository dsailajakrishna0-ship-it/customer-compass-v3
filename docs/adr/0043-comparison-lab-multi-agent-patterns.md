# 0043 — Comparison lab, multi-agent patterns on LangGraph: supervisor, hierarchical, network, handoff

- **Status:** Accepted (E5.7; measured with a scripted model and a stub CRM, no live model run)
- **Date:** 2026-11-27
- **Roadmap sub-stage:** E5.7 (the Python twin of the Java edition's J8.7; plan in [the E5 guide](../stages/E5-comparison-lab.md))

## Context

One agent that does a task is a clerk; several agents are a team, and the interesting question is **who decides who works next**. The Java lab built four answers on LangGraph4j. The Python lab builds the same four on 🟦LangGraph (one engine that can express all four, so the comparison is about the **architecture**, not the library): the same account review (the 🟪agents `crm_facts` and `deals` are plain code over the CRM tools, `analyst` and `reviewer` are model calls), the same rules, the same face.

## Decision

1. **The same face as Java's multi-agent backends:** `POST /api/v1/multi-agent/run` (`company` of at most 200 characters, optional `model`) and `GET /health`; the answer has `pattern`, `status` (`completed`, or `stopped` when a limit ended the run), `turns`, `specialists` (who ran, in order), every `decision` (`turn`, `decidedBy`, `allowed`, `chosen`, `reason`, `proposed`, and a `level` for the hierarchy), the `recommendation` (none when the run stopped early) and a `message`. 404 for an unknown company, 422 for a bad request, 503 (by kind of failure, never a library's text) when the CRM or the model is missing.
2. **The scenario and the rules are shared (`lab_common/team.py`)** because they are not the pattern: the four pieces of work, the allowed list of the supervisor, the model call, the parsing of a routing answer, and the rules that **no framework gives**: the model chooses only from a list that code builds and **no model is asked when there is one option**; an unreadable or disallowed answer is replaced and recorded (a short plain word, or `unreadable`: model text is never echoed); **no CRM text in a routing prompt**; the facts reach the analyst and the reviewer inside `<untrusted_context>`; an unreadable review counts as "revise"; at most 2 deals lookups and 1 revision; a company that is not found is a 404 with no model call.
3. **Ports 19151 to 19154** (supervisor, hierarchical, network, handoff), folders `multi-agent/<pattern>/withLangGraph`, one file per pattern holding only the pattern: the graph and its routing.
4. **Supervisor (19151):** a `supervisor` node, the four specialists, an edge from each specialist back, one conditional edge out. A turn limit of 10 decisions ends the run as `stopped`.
5. **Hierarchical (19152):** a top supervisor over two **child graphs** (`research_team`, `answer_team`), each a compiled graph added as a node with a sub-supervisor of its own and its own routing key; limits per level (4 top decisions, 6 per team) and 12 specialist runs overall; a team that hits its limit ends the whole run.
6. **Network (19153):** four peers, fully connected (a conditional edge from every peer to every peer). After its work **each peer names the next** (a model call, flags only), itself included, or FINISH. Each peer checks its own inputs (an analyst with no facts does nothing). Guards: 10 turns, 3 visits per peer, and a loop guard (the same peer three times in a row, or two peers alternating, with the board unchanged). **Nobody checks that the job is done.**
7. **Handoff (19154):** no supervisor; each agent works and names the next from **its own** list (`triage` to `researcher` by code; `researcher` to `analyst`, or itself once more while fewer than two lookups were done, by a model call in which **each target is a tool**; `analyst` to `reviewer` by code; `reviewer` back to `analyst` once, otherwise FINISH). The tool call is **read from the model's answer and never executed** (a direct model call with `bind_tools`, not an agent loop). Limits: 10 handoffs, 3 visits per agent, a repeated pair of handoffs.

## What the same review costs in each pattern (measured, a scripted happy path: facts, one deals lookup, analysis, approving review)

| | Supervisor | Hierarchical | Network | Handoff |
| --- | --- | --- | --- | --- |
| **Who decides what is next** | one coordinator, from a list code builds | a top coordinator, then one per team | every peer, any other peer | the agent that just worked, from its own list |
| **Decisions** | 5 | **9** | 4 namings | 4 |
| **Model calls** | **4** (2 for routing) | **5** (3 for routing) | **6** (4 namings) | **3** (1 hand-off) |
| **Graphs** | 1 | 3 (the top and two child graphs) | 1, fully connected | 1 |
| **Where the rules live** | one allowed-list function | one per level | nowhere central: each peer's own check | the union of the agents' lists |
| **File size** (non-blank, non-comment lines, docstrings included) | 57 | 142 | 115 | 144 |

The counts are the same as the Java lab's (4, 5, 6 and 3 model calls; 9 decisions for the hierarchy). The pattern is a small part of the code; **the shared rules file is 405 lines**, seven times the supervisor's pattern file.

## What the tests measured about the failure modes

- **Network:** a peer that names itself is stopped by the loop guard after **3 turns** (2 model calls); two peers naming each other with nothing new, after **4**; but **an analyst and a reviewer that keep changing the board slip past the loop guard** and only the per-peer cap stops them (12 or more model calls); **a peer that names FINISH too early ends the run with no recommendation** (nothing checks the job); an unreadable naming ends the chat there (there is no list to fall back on).
- **Hierarchical:** one more level means **four more decisions and one more model call** for the same review; **three of the four extra decisions are made by code**, because the answer team's order is fixed. A hierarchy pays off when each level has a real choice or the teams are owned separately; for fixed phases it is a pipeline with more bookkeeping.
- **Handoff:** the fewest routing questions (one), because each agent has few places to go; **no list allows a loop**, so the limits are the lists themselves plus a handoff cap; but a rule that spans the whole run (never draft before a review) is the union of lists and state, where the supervisor has one function.
- **Supervisor:** the simplest to audit and to bound: every decision, its allowed list and any override is in one log.

## What LangGraph did on its own (measured in `comparisons/tests/test_multi_agent.py`)

| Point | Measured |
| --- | --- |
| Graph, nodes, edges, conditional edges, child graphs | worked as documented; a child graph is given the parent's state and **its value wins on a collision**, so each level needs its own routing key |
| A brake on a looping graph | **its default limit is 10,007 steps** (a looping graph ran 10,007 times before `GraphRecursionError`), against 25 in the Java LangGraph4j: so **every limit here is ours** |
| An exception raised in a node | reaches the caller unchanged, also through a child graph (no unwrapping needed, unlike LangGraph4j) |
| A model's tool call read without running it | `bind_tools` on the chat model returns the call in the answer, **unexecuted**, in one request (Spring AI's `ChatClient` in the Java lab ran the tool and asked again) |
| The rules (allowed lists, turn limit, the 404, status-only errors, no CRM text in routing prompts, never echoing model text) | **none given**, all ours, in both languages |

**Prebuilt packages not used:** `langgraph-supervisor` 0.0.31 and `langgraph-swarm` 0.1.0 exist (checked, not added to the lock). `create_supervisor(agents, model, tools, prompt, ...)` and `create_swarm(agents, default_active_agent, ...)` build the model-decides version with handoff tools; **neither has a parameter for an allowed list or a turn limit** (their full parameter lists were read), and both are pre-1.0 releases. Using them would leave the rules above to be added around a black box, so the lab builds the graphs directly. Whether they would be a good starting point for a team without those rules is **not measured**.

## How this was run

`just comparisons-test` (268 tests, no key, no network, in CI; the multi-agent tests were run 30 times in a row without a failure). All four backends were also started once through `just` with a fake key and unreachable addresses: `GET /health` answers with the pattern, a run is a 503 `The CRM could not be reached.` (the first step in every pattern), a blank company is a 422, and the fake key is in no log line.

**Not measured:** a live model (whether it routes sensibly, how often it names something not allowed, whether a real model calls the handoff tools), real latencies and the cost in money; information lost at a team boundary (the state here carries everything whole); and `langgraph-supervisor` and `langgraph-swarm` in use. The counts are from one scripted scenario and are not general results.
