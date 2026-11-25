# E5: the comparison lab, frameworks only (plan)


The Python twin of the Java edition's **Stage J8**: the same small module built several ways, one folder per approach, so a reader opens one folder and reads exactly one approach. This page is the **plan only**; no code changes with it. Decided with the owner on 2026-11-25: full parity with J8's seven topics, **no hand-written side**, frameworks only.

**Why no hand-written side.** The application itself already is the hand-written side for every topic (our own tool loop, chunker, 🟪retrieval, memory and graph code; Stage 5.5 already compared it with the framework pieces behind `AGENT_IMPL`, `RETRIEVAL_IMPL` and `CHUNKER_IMPL`). The lab only adds what a reader cannot see in the application: how the same job looks in the frameworks themselves.

**The two approaches.** 🟦LangChain is the high-level kit (models, `@tool`, `create_agent`, loaders, splitters, 🟪vector stores, message trimming, callbacks). 🟦LangGraph is the explicit kit (a `StateGraph`, nodes, edges, a 🟪checkpointer, interrupts). In LangChain 1.x `create_agent` is built on LangGraph, so for several topics the real difference is "one call that builds it" against "you draw the graph".

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](../ai-terms.md)

## Layout

```
comparisons/                  one uv project, separate from apps/api-py (same rule as Java's comparisons/)
  common/                     shared: the HTTP face, the CRM tools, the CRM client, limits
  tool-calling/    withLangChain/  withLangGraph/
  rag-ingestion/   withLangChain/
  rag-retrieval/   withLangChain/
  observability/   withLangChain/  withLangGraph/
  agent-graph/     withLangChain/  withLangGraph/
  memory/          withLangChain/  withLangGraph/
  multi-agent/     supervisor/  hierarchical/  network/  handoff/   (each: withLangGraph/)
```

Ports 19101 and up, the mirror of Java's 18101 and up (🟪tool calling 1910x, ingestion 1911x, 🟪retrieval 1912x, observability 1913x, 🟪agent 1914x, multi-agent 1915x, memory 1916x), so the Java and Python backends can run side by side. Every backend serves the same contract as its Java twin (the same route and the same request and response), so the web app's Approach buttons can reach any of them.

## Slices (one PR each, never stacked, merged by the owner)

| Slice | What | Framework pieces to compare (to verify in each library's docs when the slice starts) |
| --- | --- | --- |
| **E5.1** | `common/`, the web app's Approach list for Python ports, and 🟪tool calling both ways | 🟦LangChain: `@tool`, `create_agent`. 🟦LangGraph: `ToolNode`, `tools_condition` in a `StateGraph` |
| **E5.2** (built: [ADR 0038](../adr/0038-comparison-lab-rag-ingestion-with-langchain.md)) | 🟪RAG ingestion with LangChain (port 19111) | document loaders, `RecursiveCharacterTextSplitter`, 🟧Gemini 🟪embeddings, `QdrantVectorStore.add_documents` |
| **E5.3** (built: [ADR 0039](../adr/0039-comparison-lab-rag-retrieval-with-langchain.md); port 19121) | RAG 🟪retrieval with LangChain | `similarity_search_with_score` on the 🟩Qdrant store, the 0.60 floor still our code |
| **E5.4** | Observability both ways | LangChain callbacks and LangGraph stream events turned into the same OpenTelemetry signals |
| **E5.5** | The 🟪agent with an approval pause both ways | LangGraph `StateGraph`, 🟪checkpointer, `interrupt`; LangChain `create_agent` with its human-approval middleware |
| **E5.6** | Conversation memory both ways | LangChain `trim_messages` and message history; LangGraph checkpointer and `thread_id`; the contract's limits (20 messages, 16,000 characters, 24 hours, 1,000 conversations) stay our code |
| **E5.7** | The four multi-agent patterns on LangGraph: supervisor, hierarchical, network, handoff | `langgraph-supervisor` and `langgraph-swarm` where they fit, plain graphs elsewhere |
| **E5.8** | The side-by-side write-up and the interview notes | measured: lines of code, what the library gave for free, what stayed ours |

**Rules carried over from Java.** The modules do not change the application; no keys are needed for the tests (scripted stand-ins for the model and Qdrant); every backend is run once through `just` with a fake key and a dead address before its PR; each slice writes an ADR with what the library did without our code and what it did not, with measured evidence. Anything not measured is written as "not measured". No unverified library name is promised in a slice's PR; each slice checks the real API first.

## Open points (decide when the slice starts)

- Ingestion and 🟪retrieval have only a 🟦LangChain side because 🟦LangGraph does not own those jobs. If you also want 🟦LlamaIndex as a second approach for them, say so and it becomes E5.2b and E5.3b.
- Observability's "both ways" may be only LangChain if the LangGraph events add nothing different; the slice says so in its ADR.
- No live recordings against real models without your explicit "go"; the tests stay key-less.
