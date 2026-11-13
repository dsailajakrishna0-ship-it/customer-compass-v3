# 0022 — Tracing with OpenTelemetry, shown in a self-hosted Langfuse

- **Status:** Accepted
- **Date:** 2026-11-13
- **Roadmap sub-stage:** 5.1

## Context

Until now the only record of what a request did is a log line per request and the audit tables (`tool_audit_log`, `security_audit_log`). They answer "what was done and was it allowed". They do not answer "why was that answer slow", "which model really answered after the fallback", "how many tokens did this agent run use" or "which step of the agent failed". The roadmap asks for a trace for every agent run (exit criterion of 5.1), using a self-hosted Langfuse.

Constraints from earlier decisions: everything must run on free tiers and on one laptop ([ADR 0010](0010-cloud-only-models.md)); optional features follow the reranker's rules ([ADR 0019](0019-hybrid-search-and-reranker.md)): off by default, and a failure never breaks a request; the default `docker compose up` must stay light.

## Decision

1. **Spans are made with OpenTelemetry, not with a Langfuse SDK.** OpenTelemetry is the standard way to describe a request as a tree of timed steps; Langfuse accepts it natively on its `/api/public/otel` endpoint. The code in the API depends only on `opentelemetry-api` and `-sdk`, so the receiver can be changed (Langfuse today, any OTLP receiver tomorrow) without touching a route. Pinned: `opentelemetry-api`, `-sdk` and `-exporter-otlp-proto-http` **1.45.2** (the current release, checked on PyPI on 2026-11-13).
2. **One small module, `app/tracing.py`,** is the only place that knows OpenTelemetry. Everything else calls `tracing.span(...)`. With tracing off the call does nothing.
3. **What becomes a span** (each is a child of the request's span):
   | Span | Langfuse type | Where | Attributes (never text) |
   | --- | --- | --- | --- |
   | the request, `POST /api/v1/chat/rag` | span (the root) | `RequestIdMiddleware` | method, path, status, request id |
   | `llm.generate` | generation | `gateway.generate` | requested and answering model, input and output tokens, latency, fallback used and from, tool calls |
   | `retrieval` | retriever | `retrieve_relevant_chunks` | mode, top_k, scoped to a company, reranker, results, best and weakest similarity, question length |
   | `tool.<name>` | tool | `_run_tool_call` | tool, MCP server, argument **names**, confirm flag, result status |
   | `agent.run` and one span per step of the agent's own `Trace` | agent, tool or span | `run_account_review`, `Trace.record` | status, steps, model calls, revisions; per step: index, kind, status, sizes |
   | `agent.resume` | agent | `resume_run` | confirm, whether a paused run was found |
   The agent's steps reuse the `Trace` the UI already shows (`Trace.record` also emits a span, back-dated by the step's duration), so the UI and Langfuse cannot disagree and no node had to change.
4. **The request id is the trace id.** `RequestIdMiddleware` already gives every request a 32-character hex id (and the `X-Request-ID` header). When the id is a valid trace id, the request's trace uses it, so one id finds the log lines, the response header and the trace in Langfuse. A caller's own token (not 32 hex characters) stays an attribute and the trace gets a fresh id.
5. **Off by default, and content is a second switch.** `TRACING_ENABLED=false` is the default: no exporter, no thread, no network. `TRACING_CAPTURE_CONTENT=false` is the default even when tracing is on: spans carry counts, names, sizes and similarity scores. Only when it is true do the question text, the model's answer and the agent steps' shortened summaries go out, because those can contain customer data. Attribute names that look like secrets (`api_key`, `secret`, `password`, `authorization`, ...) are dropped, and text is cut to 200 characters.
6. **Tracing never breaks a request.** Every call into OpenTelemetry is wrapped; a span that cannot start is a no-op; an exception from the traced code passes through unchanged and the span records only its *type* (an exception message can hold a key or a customer's text). Export happens in a background thread with a 5-second timeout (`BatchSpanProcessor`), so a slow or dead Langfuse costs the request nothing. A failure to set up tracing at start-up is logged and the API starts without it.
7. **Langfuse is self-hosted behind an optional compose profile,** `observability` (`docker compose --profile observability up -d langfuse-web langfuse-worker`). It is Langfuse 4 (pinned to **4.79.0**, the current release on 2026-11-13): a web service, a worker, Postgres, ClickHouse, Redis and MinIO, adapted from Langfuse's own compose file and cut down to what a local run needs. Langfuse recommends 4 CPU cores and 16 GiB of memory for it. Only the web UI is published, on `127.0.0.1`. The stack's Postgres uses the Alpine image (the Debian image crashes on some CPUs). Every secret in the file is a local-development placeholder with an environment override.
8. **The API sends to `/api/public/otel`** with a Basic auth header made from the project's public and secret key and the header `x-langfuse-ingestion-version: 4` (so spans appear in real time), as Langfuse's own documentation describes. The keys are settings (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`), never logged, and no header is sent when they are empty.
9. **The audit tables stay exactly as they are.** A trace is for understanding performance and behaviour and may be sampled or deleted; an audit row is a record of what was done and is kept (`SECURITY_AUDIT_RETENTION_DAYS`). Tests check that an injection attempt still reaches the security audit log with tracing on.

## Alternatives considered

- **The Langfuse Python SDK** (`@observe`). Less code, but the routes would import a vendor SDK and the choice of receiver would be baked into the code. OpenTelemetry costs one small module and keeps the receiver replaceable.
- **Auto-instrumentation packages** (FastAPI, httpx, asyncpg). They add many spans we do not need (every SQL statement) and a larger dependency tree; Langfuse shows LLM-relevant spans best. The spans we want are the five above.
- **Langfuse Cloud or LangSmith.** Hosted: traces leave the machine, and the project's rule is free and local first. Langfuse Cloud accepts the same OTLP, so switching is two settings (`TRACING_ENDPOINT` and the keys).
- **Storing traces in Postgres.** Would reinvent a UI and a query language for something Langfuse already does, and would mix performance data with the audit tables.
- **Tracing the MCP servers too.** The tool call is traced where the chat route makes it; propagating the trace into the FastMCP and Spring Boot processes (W3C `traceparent`) is possible later and would show the server's own time inside the tool span.

## Consequences

- Three small dependencies enter the API image; they are imported only when tracing is on or a span is made, and the default behaviour is unchanged.
- The optional stack is heavy (six containers, several GB of images). It is meant for looking at traces while developing, not for the default setup.
- Traces cannot be searched by customer, because customer text is not recorded by default. With content capture on, they can, and the Langfuse project then holds customer data: treat it like the database.
- The FastMCP server and the Java tool server are not instrumented; a tool span shows the round trip, not the server's internals.
- The same spans can later carry evaluation scores (5.2) and be the data source for comparing the agentic-retrieval variant (5.4) and the framework seams (5.5).
