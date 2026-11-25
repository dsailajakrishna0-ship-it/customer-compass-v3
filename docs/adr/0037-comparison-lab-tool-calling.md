# 0037 — Comparison lab, tool calling: LangChain's `create_agent` against a LangGraph graph we draw

- **Status:** Accepted (E5.1; measured with a scripted model, no live model run)
- **Date:** 2026-11-25
- **Roadmap sub-stage:** E5.1 (the Python twin of the Java edition's J8.1; plan in [the E5 guide](../stages/E5-comparison-lab.md))

## Context

The Java lab builds tool calling by hand, with Spring AI and with LangChain4j behind one HTTP face. The Python lab has no hand-written side (the application is that side) and compares the two 🟦frameworks we already use: 🟦LangChain (`create_agent`, `@tool`) and 🟦LangGraph (`StateGraph`, `ToolNode`).

## Decision

1. **A separate uv project, `comparisons/`**, outside `apps/api-py`, one folder per approach (`tool-calling/withLangChain`, `tool-calling/withLangGraph`) and `common/` for what they share: the types, the CRM client and the two read-only tools (`get_company_summary`, `get_open_deals`, the contract in `contracts/mcp-tools.json`), the system prompt, the HTTP face (`POST /api/v1/chat/tools`, `GET /health`, same body and answer shape as the application's route, no prompt guard) and a scripted stand-in for the model.
2. **Ports 19101 (withLangChain) and 19102 (withLangGraph)**, the mirror of Java's 18101 to 18103. Settings: `PORT`, `CRM_BASE_URL`, `LLM_BASE_URL`, `OPENROUTER_API_KEY`, `MODEL` (default `meta-llama/llama-3.1-8b-instruct`, as in Java).
3. **The same two tools in both approaches, written with LangChain's `@tool`** inside each approach's own file, so a reader sees them next to the loop. The tool result is wrapped as `<untrusted_context>` data inside the tool (the framework does not do it).
4. **withLangChain:** `create_agent(model, tools, system_prompt=..., middleware=[ModelCallLimitMiddleware(run_limit=5, exit_behavior="end")])`.
5. **withLangGraph:** a `StateGraph` with a `model` node (`model.bind_tools`), LangGraph's prebuilt `ToolNode`, a counter node, a conditional edge after the model (tools while rounds are under 4, a last answer without tools when the model still asks, otherwise end).
6. **No live recording.** Behaviour is measured against a scripted model; how a real model behaves with these tools is not measured here.

## What the libraries did without our code (measured in `comparisons/tests/test_tool_calling.py`)

| Behaviour | withLangChain | withLangGraph |
| --- | --- | --- |
| The loop: model, run the tools it asked for, model again | `create_agent` | our graph, `ToolNode` runs the tools |
| The tool's JSON Schema | written from the signature and docstring by `@tool` (name, description, `company_name` as a required string, its description) and equal to the contract | the same, the same `@tool` |
| A call to a tool that does not exist | answered to the model with an error text ("not a valid tool, try one of ..."), no exception | the same |
| A missing argument, and a wrong-typed plus an extra argument | answered to the model with "Error invoking tool ... " naming `company_name`, no exception; the number 5 for a string is **refused** (Spring AI in the Java lab coerced it) | the same |
| Tools that ran | listed in `toolsUsed` when answered (a failed call counts, a call nobody ran does not) | the same |

## What each needed from us

| Rule | withLangChain | withLangGraph |
| --- | --- | --- |
| At most 4 rounds that ask for tools | `ModelCallLimitMiddleware`. At the limit the loop **ends with the library's own text** (`Model call limits exceeded: run limit (5/5)`) as the answer: there is no last model answer | a counter node and the routing function; at the limit one more model call **with tools switched off** gives a real answer (the same behaviour as the Java hand-written loop) |
| Results are data, not instructions | the wrapper inside each tool | the same |
| System prompt | `system_prompt=` | a `SystemMessage` put in front in the model node |

**Size** (non-blank, non-comment lines of each approach's file, docstrings and the two tool definitions included): withLangChain 76, withLangGraph 112. The 36 extra lines are the state with a counter, the routing and the last-answer node.

**Left out in both, on purpose or not yet built:** at most 4 tool calls in one reply (the Java loop caps this; neither framework does by default and it was not built here), the prompt guard, model fallback, tracing and the audit log (the application has them).

## How this was run

`just comparisons-test` (44 tests, no key, no network, also in CI). Each backend was also started once through `just` with a fake key and unreachable CRM and model addresses: both answer `GET /health`, a bad request is a 422 with a short `detail`, and a question gets a 503 `The model call failed (OpenAIConnectionError).` (the kind of error, never the library's text); the fake key appears in no log line.

## Consequences

- The framework with the least code (`create_agent`) gives up the last real answer at the round limit; if that matters, the middleware's `exit_behavior="error"` or the graph is the choice. Which one is better with a real model is **not measured** and is left to the write-up (E5.8) and to a later live run on the owner's "go".
- The web app does not get an Approach switch for these ports in E5.1 (the Python web app has no Approach buttons; the Java repo's web app has them).
