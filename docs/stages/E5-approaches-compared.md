# E5.8: the comparison lab, side by side

The write-up of the Python comparison lab ([plan](E5-comparison-lab.md), code in [`comparisons/`](../../comparisons/README.md)): seven modules, each built with 🟦LangChain and 🟦LangGraph where both fit, against one contract, with ADRs [0037](../adr/0037-comparison-lab-tool-calling.md) to [0043](../adr/0043-comparison-lab-multi-agent-patterns.md). It is the Python twin of the Java edition's J8 write-up. Everything here comes from the code, the tests and those ADRs.


**Not measured, anywhere in this lab:** a live model or a live 🟪embedding service (every number is from a scripted model, a fake embedding model or a stub CRM, plus a real 🟩Qdrant server for storage), real latencies, cost in money, and answer quality. Counts of model calls, decisions and lines are from scripted scenarios, not general results.

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](../ai-terms.md)

## The seven modules at a glance

| Module (ADR) | withLangChain | withLangGraph | Lines (approach file) | What decided the comparison |
| --- | --- | --- | --- | --- |
| **🟪Tool calling** ([0037](../adr/0037-comparison-lab-tool-calling.md)) | `@tool` + `create_agent` | a `StateGraph` with `ToolNode` | 76 and 112 | the **round limit**: 🟦LangChain's middleware ends with its own canned text; the graph forces a real last answer |
| **🟪RAG ingestion** ([0038](../adr/0038-comparison-lab-rag-ingestion-with-langchain.md)) | loader, splitter, 🟧Gemini 🟪embeddings, `QdrantVectorStore` | not its job | 154 | **order**: `from_documents(force_recreate=True)` empties the collection before embedding |
| **🟪RAG 🟪retrieval** ([0039](../adr/0039-comparison-lab-rag-retrieval-with-langchain.md)) | `similarity_search_with_score` | not its job | 115 | **the scale of the score**: two helpers rescale to `(cosine + 1) / 2` |
| **Observability** ([0040](../adr/0040-comparison-lab-observability.md)) | callbacks | stream updates | 69 and 64 | **what each hook can see**: callbacks miss a tool that does not exist; stream updates miss a failed node and per-tool time |
| **🟪Agent with an approval pause** ([0041](../adr/0041-comparison-lab-agent-with-approval-pause.md)) | `create_agent` + human-approval middleware | `StateGraph`, `interrupt()`, 🟪checkpointer | 160 and 104 | **who decides the steps**: the model (3 model calls, may never pause) or our graph (1 model call) |
| **Conversation memory** ([0042](../adr/0042-comparison-lab-conversation-memory.md)) | message history + `trim_messages` | checkpointer + thread id | 119 and 128 | **deprecation** of the LangChain classes; the checkpointer **cannot prune** |
| **🟪Multi-agent patterns** ([0043](../adr/0043-comparison-lab-multi-agent-patterns.md)) | not used | four patterns on one engine | 57, 142, 115, 144 | **who decides what is next**; the rules are 405 shared lines |

The shared code that is not the comparison: the HTTP faces, the CRM tools, the scripted model and, for memory and the teams, the rules (`lab_common/`). **268 tests**, none needing a key or the network, run in CI.

## What the frameworks gave, and what stayed ours

| | Gave without our code | Stayed ours in every module |
| --- | --- | --- |
| **🟦LangChain** | the model wrapper and its token usage; `@tool` schemas written from a signature and a docstring; a tool loop; a 🟪text splitter with character offsets; a 🟧Gemini 🟪embedding class that batches 100 per request and puts the key in a header; a 🟩Qdrant store; `trim_messages` for a window | the **rules**: limits and what happens at them, wrapping tool results as data, the floor on a 🟪cosine, the order of embed-then-replace, the length check of a vector, error text that never echoes a library's message |
| **🟦LangGraph** | state, nodes, edges, conditional edges, child graphs; a 🟪checkpointer; `interrupt()` and `Command(resume=...)`; stream updates; an exception raised in a node reaching the caller unchanged | **every limit** (its own is 10,007 steps), the allowed lists, who may pause what, bounding memory, and the deciding of who works next |

**The pattern is a small part of the code; the rules around it are most of it.** The shared rules file of the 🟪multi-agent module (405 lines) is seven times the supervisor pattern's own file (57 lines).

## Ten things worth remembering

1. **A framework's default is not your contract.** The round limit, the decline path, the failed-turn behaviour and the score scale all differed from the application's rules in at least one approach.
2. **Find out the scale of a score before you hand it a calibrated number.** 🟦LangChain's relevance-score helper and its threshold retriever rescale a 🟪cosine to `(cosine + 1) / 2`: a floor of 0.60 there would keep a 🟪chunk of cosine 0.3.
3. **Order matters when a library "recreates" for you.** `QdrantVectorStore.from_documents(force_recreate=True)` empties the collection before it embeds; a failed 🟪embedding run would lose the old data. Embed first, then replace.
4. **The obvious design can store a failed turn.** The simplest 🟦LangGraph memory design wrote the question of a failed turn into the history; a separate `new` key in the state fixed it.
5. **Check the deprecation notes.** In a fresh interpreter LangChain warns that `InMemoryChatMessageHistory` and `RunnableWithMessageHistory` are deprecated in favour of LangGraph persistence, and that `langchain-community` (the home of `TextLoader`) is being sunset.
6. **A 🟪checkpointer keeps everything unless you make it forget.** `InMemorySaver` keeps three checkpoints per turn and its `prune` is not implemented; memory is bounded only because the thread is rewritten as one checkpoint after each turn.
7. **Who decides the steps changes the cost and the risk.** The same approval run takes 1 model call when our graph decides and 3 when the model does, and the model-decided run never pauses if the model skips the tools.
8. **Observation hooks see different things.** Callbacks see a failed model call and miss a tool that does not exist; stream updates see the unknown tool and miss a failed node, and give no time per tool.
9. **The model proposes, code decides.** In every 🟪multi-agent pattern the model picks only from a list code builds, and a network, which has no such list, can be stopped only by blunt limits and cannot tell that the job is done.
10. **Real services find what fakes hide.** Only a real 🟩Qdrant server showed that a missing collection is a 404 response, not a `ValueError`; and the version of `qdrant-client` that `langchain-qdrant` allows (below 1.16) is older than the application's.

## When to choose which

| Situation | Choose |
| --- | --- |
| A tool-calling 🟪agent where the default loop and its limits are acceptable, and the fewest lines win | 🟦LangChain `create_agent` |
| A flow where you need a forced last answer, an explicit pause, per-step events or your own limits | 🟦LangGraph, drawn by hand |
| Memory for a new project | LangGraph persistence (LangChain itself points there), with your own pruning and time limits |
| Reading documents and storing vectors | The framework classes are short; write the order, the checks and the errors yourself, and do not take `langchain-community` for a loader you can write in a few lines |
| A team of agents | Start with a **supervisor** (simplest to audit); add a hierarchy only when each level has a real choice; use a network only with guards you have tested; use handoff for routing to specialists |

## What this lab did not do

No live model or 🟪embedding call (a run needs your keys and your "go"); no durable store (every approach loses its state on a restart, unlike the application's Postgres); no web-app Approach switch for the Python ports; no use of `langgraph-supervisor` or `langgraph-swarm` (they exist, with no parameter for an allowed list or a turn limit); no 🟦LlamaIndex side for ingestion and 🟪retrieval.
