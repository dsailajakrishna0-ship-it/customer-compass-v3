# Stage 5 — Observability and evals: see what the system did

> **Level:** beginner friendly; read [Stage 3](03-langgraph-port.md) for the 🟪agent steps this stage makes visible. **Reading time:** about 15 minutes so far (this guide grows with 5.2 to 5.5).
> **Status:** in progress. **5.1 (tracing) is done; 5.2 (answer-quality 🟪evals), 5.3 (🟪guardrail comparison), 5.4 and 5.5 are next.**
> **Roadmap:** [Stage 5](../roadmap.md#stage-5--observability-and-evals) · **Decisions:** [ADR 0022](../adr/0022-tracing-with-opentelemetry-and-langfuse.md)

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](../ai-terms.md)

## In one minute

Until now the only record of a request was one log line and the audit tables. They say *what* was done and *whether it was allowed*. They do not say *why it was slow*, *which model really answered after a fallback*, *how many tokens a run used* or *which 🟪agent step failed*. A **trace** answers those.

| Shop idea | Project idea | In the code |
| --- | --- | --- |
| A receipt for one customer visit, listing every counter they stopped at | **A trace**: everything one request did | one trace per HTTP request, `app/middleware.py` |
| One line on the receipt (counter, minutes, what was bought) | **A span**: one timed step | `tracing.span()` in `app/tracing.py` |
| The counters are nested: "checkout" contains "scan item" | **Parent and child spans** | `agent.run` contains one span per step |
| The shop manager's screen that shows all receipts | **🟦Langfuse** | optional compose profile `observability` |
| A standard receipt format every till can print | **OpenTelemetry** | the same data could go to any other viewer |

## Concept 1 — Tracing (5.1)

**Trace, span, attributes.** A trace is the tree of spans for one request. A span has a name, a start and an end, a status, and **attributes**: small labelled facts such as `gen_ai.usage.input_tokens=69` or `retrieval.results=4`. The tree for one 🟪agent run looks like this:

![What one request records: the HTTP request span contains the model, retrieval, tool and agent spans](../img/diagrams/stage5-trace-map.png)

**Why OpenTelemetry and not the 🟦Langfuse library.** OpenTelemetry is the neutral standard: our code creates spans, and an *exporter* sends them wherever we choose. Langfuse accepts that format directly, so nothing in our code names Langfuse. Switching the viewer (or comparing it with another one in 5.5) is a setting, not a rewrite. Langfuse reads a few attribute names to decide how to draw a span (`langfuse.observation.type`: `generation` for a model call, `retriever`, `tool`, `agent`), and the `gen_ai.*` names for the model and token counts.

**The request id is the trace id.** Every request already has an id (1.1) that is in the log lines and the `X-Request-ID` header. When it is a 32-character hex id, the trace uses it as its trace id, so one id finds the logs *and* the trace. A caller's own free-form id cannot be a trace id, so that request gets a random trace id and the id stays an attribute.

**The privacy rule.** A trace store is a second place data can leak from, so spans carry **counts, names and sizes, never content**: tokens, milliseconds, how many results, which tool and the *names* of its arguments, not their values. Questions, answers, 🟪chunk text, tool arguments and results are only recorded when you set `TRACING_CAPTURE_CONTENT=true`, a second switch that is off by default. Attribute names that look like secrets are dropped, and an exception is recorded by its type only (its message could hold user text).

**It can never break a request.** Tracing is off by default (`TRACING_ENABLED=false`). When it is on, a broken exporter, an unreachable Langfuse or a failure while creating a span is logged once and the request carries on, the same rule as the 🟪reranker (ADR 0019). Exports are batched in the background, so a slow Langfuse does not slow the answer.

**The audit tables stay.** Traces are for *understanding* and expire; the audit tables are the *record*. The agent's own step list is still saved, and each step is also emitted as a span from the same place (`Trace.record`), so the two never disagree. One consequence: the audit trace marks "no company found" as an `error` step, so its span shows as an error too, even though it is a normal outcome for a question that names no company.

**Seeing it.** `docker compose --profile observability up -d` adds Langfuse (web, worker, Postgres, ClickHouse, MinIO, Redis) on `127.0.0.1:3000` only. The profile is optional because that is six more containers; the default stack is unchanged. See [testing guide 5.1](../testing-guide.md#stage-51-tracing-with-langfuse).

**Rule to remember.** *A trace is a receipt, not a copy of the conversation. Record how long and how many; record what only when someone chose to, and never let the recording break the thing being recorded.*

---

## Code tour: what changed in 5.1

| | Where | What |
| --- | --- | --- |
| 🟢 | `app/tracing.py` | Setup, the `span()` helper, the request-id trace id, attribute cleaning, the "never raise" rule |
| 🟡 | `app/middleware.py` | One span per request (not `/health`) |
| 🟡 | `app/llm/gateway.py` | A `generation` span per model call: model, tokens, latency, fallback |
| 🟡 | `app/rag/retrieve.py` | A `retriever` span: mode, results, similarity range |
| 🟡 | `app/routes/chat.py` | A `tool` span per executed 🟪tool call |
| 🟡 | `app/agent/trace.py`, `app/agent/workflow.py` | One span per 🟪agent step under `agent.run` and `agent.resume` |
| 🟡 | `app/config.py`, `app/main.py`, `.env.example` | `TRACING_*` and `LANGFUSE_*` settings; start and stop |
| 🟡 | `docker-compose.yml` | The optional `observability` profile |
| 🟢 | `tests/test_tracing.py`, `tests/agent_internals/test_agent_tracing.py` | 34 tests with an in-memory exporter, no 🟦Langfuse needed |
