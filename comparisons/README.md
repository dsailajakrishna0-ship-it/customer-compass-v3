# Comparisons (E5)

The same module of the application built with 🟦LangChain and with 🟦LangGraph, one folder per approach, so a reader opens one folder and reads exactly one approach. The plan is in [the E5 guide](../docs/stages/E5-comparison-lab.md). These modules are **separate from the application** (`apps/api-py`) and change nothing in it. There is no hand-written side: the application is that side.

```
comparisons/
  pyproject.toml          one uv project (`just comparisons-test`)
  common/lab_common/      shared: types, CRM client and tools, HTTP face, scripted model for tests
  tool-calling/
    withLangChain/        E5.1: @tool and create_agent (port 19101)
    withLangGraph/        E5.1: a StateGraph with ToolNode (port 19102)
  rag-ingestion/
    withLangChain/        E5.2: TextLoader, RecursiveCharacterTextSplitter, Gemini embeddings, QdrantVectorStore (port 19111)
  rag-retrieval/
    withLangChain/        E5.3: QdrantVectorStore.similarity_search_with_score, the floor in our code (port 19121)
  observability/
    withLangChain/        E5.4: the tool-calling chat observed through LangChain callbacks (port 19131)
    withLangGraph/        E5.4: the tool-calling chat observed through LangGraph stream updates (port 19132)
  tests/
```

The tool-calling backends serve `POST /api/v1/chat/tools` (the application's body and answer shape, without the prompt guard); the ingestion backends serve `POST /api/v1/ingest` (optional `{"limit": n}`); the retrieval backends serve `POST /api/v1/retrieve` (`{"query", "topK", "minSimilarity"}`); every backend serves `GET /health`.

| Command | What it does |
| --- | --- |
| `just comparisons-test` | Lint and every test; no keys, no network |
| `just comparisons-tool-calling-with-langchain` | Starts the withLangChain backend on port 19101 (needs `OPENROUTER_API_KEY` to answer and the application up for the CRM routes) |
| `just comparisons-tool-calling-with-langgraph` | Starts the withLangGraph backend on port 19102 (same settings) |
| `just comparisons-ingest-with-langchain` | Starts the withLangChain ingestion backend on port 19111 (needs `GOOGLE_API_KEY` and `just qdrant`; replaces the collection `compare_withlangchain`) |
| `just comparisons-retrieve-with-langchain` | Starts the withLangChain retrieval backend on port 19121 (needs `GOOGLE_API_KEY`, `just qdrant` and a prior ingestion run) |
| `just comparisons-observe-with-langchain` | Starts the observed withLangChain tool-calling backend on port 19131 (`TELEMETRY_ENABLED=true` to record; needs `OPENROUTER_API_KEY` and the application up); then `GET /api/v1/observability/recent` |
| `just comparisons-observe-with-langgraph` | Starts the observed withLangGraph tool-calling backend on port 19132 (same settings) |

Settings (tool calling): `PORT`, `CRM_BASE_URL` (default `http://localhost:8001`), `LLM_BASE_URL` (default OpenRouter), `OPENROUTER_API_KEY`, `MODEL` (default `meta-llama/llama-3.1-8b-instruct`).

Settings (ingestion): `PORT` (19111), `SOURCE_DIR` (`../sample-data/documents`), `GOOGLE_API_KEY`, `GOOGLE_EMBEDDING_MODEL` (`gemini-embedding-001`), `EMBEDDING_DIMENSIONS` (768), `QDRANT_URL` (`http://localhost:26333`).
Settings (retrieval): `PORT` (19121), `GOOGLE_API_KEY`, `GOOGLE_EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`, `QDRANT_URL` as for ingestion.

To run the two tests that need a real Qdrant: `docker run -d --name cc-e5-qdrant -p 26335:6333 qdrant/qdrant:v1.20.0`, then `QDRANT_URL=http://localhost:26335 just comparisons-test`.
