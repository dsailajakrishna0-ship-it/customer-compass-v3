# Comparisons (E5)

The same module of the application built with 🟦LangChain and with 🟦LangGraph, one folder per approach, so a reader opens one folder and reads exactly one approach. The plan is in [the E5 guide](../docs/stages/E5-comparison-lab.md). These modules are **separate from the application** (`apps/api-py`) and change nothing in it. There is no hand-written side: the application is that side.

```
comparisons/
  pyproject.toml          one uv project (`just comparisons-test`)
  common/lab_common/      shared: types, CRM client and tools, HTTP face, scripted model for tests
  tool-calling/
    withLangChain/        E5.1: @tool and create_agent (port 19101)
    withLangGraph/        E5.1: a StateGraph with ToolNode (port 19102)
  tests/
```

Every backend serves `POST /api/v1/chat/tools` (the application's body and answer shape, without the prompt guard) and `GET /health`.

| Command | What it does |
| --- | --- |
| `just comparisons-test` | Lint and every test; no keys, no network |
| `just comparisons-tool-calling-with-langchain` | Starts the withLangChain backend on port 19101 (needs `OPENROUTER_API_KEY` to answer and the application up for the CRM routes) |
| `just comparisons-tool-calling-with-langgraph` | Starts the withLangGraph backend on port 19102 (same settings) |

Settings: `PORT`, `CRM_BASE_URL` (default `http://localhost:8001`), `LLM_BASE_URL` (default OpenRouter), `OPENROUTER_API_KEY`, `MODEL` (default `meta-llama/llama-3.1-8b-instruct`).
