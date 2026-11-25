# 0040 — Comparison lab, observability: LangChain callbacks against LangGraph stream updates

- **Status:** Accepted (E5.4; measured with a scripted model, no live model run)
- **Date:** 2026-11-26
- **Roadmap sub-stage:** E5.4 (the Python twin of the Java edition's J8.4; plan in [the E5 guide](../stages/E5-comparison-lab.md))

## Context

The application traces a question with OpenTelemetry (ADR 0022). The Java lab captured the same signals three ways. Here the two 🟦frameworks have two different hooks for it: 🟦LangChain **callbacks** (a handler the run reports to) and 🟦LangGraph **stream updates** (one event per node that ran). The comparison is which signals each one can give.

## Decision

1. **The same signals as the Java lab and the application:** a trace per question with a root span `chat.request`, one `llm.generate` span per model call (GenAI attributes, token counts) and one `tool.<name>` span per tool the model asked for; metrics `cc.chat.requests`, `cc.chat.model_calls`, `cc.chat.tool_calls`, `gen_ai.client.token.usage`, `cc.chat.request.duration`. **Names, counts, ids and durations only, never content** (no question, answer, document text or tool argument value; a tool name that is not one we offer is recorded as `unknown`).
2. **One shared recorder, `lab_common/telemetry.py`:** the only place that knows OpenTelemetry. Spans go to a bounded in-memory buffer (200 spans). `GET /api/v1/observability/recent` shows the latest traces and the metrics when the backend runs with `TELEMETRY_ENABLED=true`, otherwise it is a 404 with a hint.
3. **The observed variants reuse the E5.1 tool-calling approaches** (a subclass with one hook each), so the loop is not copied: `observability/withLangChain` (port 19131) hands LangChain a `BaseCallbackHandler` in the run's config; `observability/withLangGraph` (port 19132) runs `graph.stream(..., stream_mode="updates")` and reads each event.

## What each hook gave (measured in `comparisons/tests/test_observability.py`)

| Signal | withLangChain (callbacks) | withLangGraph (stream updates) |
| --- | --- | --- |
| A span per model call, with tokens | yes: `on_chat_model_start` and `on_llm_end` (the time is measured between them; tokens from the reply's usage) | yes: the `model` and `final_answer` events carry the reply; the time is the time **between two events** |
| A failed model call | **yes**: `on_llm_error` gives an `llm.generate` span with outcome `error` | **no**: a node that raised yields no event, so only the failed root span shows it |
| A tool that ran | yes: `on_tool_start` and `on_tool_end` give one span per tool with **its own duration** | yes, but the `tools` event covers **all tools of the round together**, so their time is shared equally (there is no time per tool) |
| Bad arguments (missing or wrong type) | yes: `on_tool_error` with a validation error becomes `invalid_arguments` | yes: the tool message has status `error` and the arguments are checked by our own rule (`arguments_are_valid`) to tell `invalid_arguments` from `tool_error` |
| A tool that does not exist | **never reaches the callbacks** (measured: no tool event at all); found afterwards by comparing what the model asked for with what the callbacks saw, and recorded as `tool.unknown` with outcome `invalid_call` | yes: the tool message arrives in the `tools` event; recorded the same way |
| The order of the nodes | not visible | the events are `model`, `tools`, `count_round`, `model` for one tool round |

**Size** (non-blank, non-comment lines, docstrings included): the LangChain observer 69, the LangGraph observer 64, the shared recorder `telemetry.py` 213 and the shared request wiring `observed.py` 33.

## What stayed ours in both

The span and metric names, the rule that content is never recorded, the bounded buffer, the JSON route, the fixed outcome words and the classification of a tool call.

## How this was run

`just comparisons-test` (118 tests, no key, no network, in CI). Both observed backends were also started once through `just` with a fake key, unreachable addresses and `TELEMETRY_ENABLED=true`: a question gets the 503 `The model call failed (OpenAIConnectionError).` and `GET /api/v1/observability/recent` shows, for withLangChain, an `llm.generate` span with outcome `error` plus the failed `chat.request`, and for withLangGraph only the failed `chat.request` (the difference in the table). The fake key is in no log line.

**Not measured:** a real model's token counts and timings, an exporter to a real collector (Langfuse, LangSmith or OTLP; the application's tracing does that), and the cost of observation in speed.
