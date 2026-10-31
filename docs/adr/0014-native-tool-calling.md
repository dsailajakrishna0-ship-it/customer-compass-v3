# 0014 — Native tool calling with Pydantic schemas

- **Status:** Accepted
- **Date:** 2026-10-31
- **Roadmap sub-stage:** 2.1

## Context

V2's `/chat/tools` route taught the model a text format: reply with a fenced `tool_call` block containing JSON, which the route found with a regular expression. That existed because the small local model could not use the providers' structured tool calling. The local model is gone ([ADR 0010](0010-cloud-only-models.md)), and the gateway ([ADR 0009](0009-litellm-gateway.md)) already speaks to every model in one format.

The text format had weaknesses beyond being hand-rolled: a malformed block cost a whole turn, the tool list and arguments lived in prompt prose instead of a schema, and the safety rule "the model must not confirm a task itself" was enforced by overwriting an argument the model was still allowed to send.

## Decision

Use the providers' native tool calling, through the gateway.

- **`generate(..., tools=, tool_choice=)`** passes OpenAI-style function definitions to LiteLLM and returns the model's `tool_calls` parsed into `ToolCall` objects. Arguments that are not valid JSON become a `ToolCall` with `error` set, never an exception.
- **`app/mcp/schemas.py`** holds one Pydantic model per tool. Its JSON Schema is what the model sees; it also validates what the model sends (`extra="forbid"`, length limits). Descriptions still come from the tool server; a tool with no model is never offered.
- **`confirm` is not part of the model's schema.** The route sets it from the user's own latest message. A model that sends it anyway gets a validation error as a tool result, and nothing runs.
- **The loop** (still bounded: 4 iterations, at most 4 calls per reply) answers every requested call with a `tool` message carrying the call's id, as providers require. Invalid, unknown or failing calls become error results the model can read and correct. After the last iteration one final text answer is forced with `tool_choice="none"`.
- The response shape (`message`, `toolsUsed`, `usage`, `guardrail`) is unchanged; so are the tools, MCP and the audit log. Tool output is still scanned and wrapped as untrusted context.

## Alternatives considered

- **Keep the fenced text protocol:** works with any model, but is the thing native calling replaces; its only reason to exist is gone.
- **Take the schema from the MCP server:** one source of truth, but then `confirm` (and any future server-only argument) would be offered to the model. Our models are an explicit allowlist of what a model may pass.
- **Structured-output / JSON mode instead of tools:** a different feature (one structured answer, not choosing among tools); Stage 3 may use it for graph nodes.

## Consequences

- **Not verified against real models.** No OpenRouter key was available, so no free model has been seen making a tool call through this code. Free models differ in tool-calling support: one that refuses is expected to fail and the gateway to fall back to the next, but that behaviour is untested. The offline tests use a scripted provider and a fake tool server.
- **The `tools` eval baseline is stale in a second way:** it was taken with the local model and the old protocol ([ADR 0010](0010-cloud-only-models.md)). It must be re-taken with a hosted model; until then `just eval` skips it.
- A model that returns text instead of calling a tool (a weak model) simply answers without tools: safe, but less useful. The re-taken baseline will show how often.
- Adding a tool now means two edits: the tool server and a model in `schemas.py`; a test fails if they disagree.
