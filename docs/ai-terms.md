# AI terms, A to Z

> Generated from [`ai-terms.yaml`](ai-terms.yaml) by `just ai-terms`. Do not edit by hand.

Building with language models brings a lot of new words, mixed in with ordinary software words. This project marks the AI ones with a coloured square the first time they appear in each section of the main docs, so you can tell "this is the AI part" from "this is normal engineering" at a glance.

| Marker | Meaning | Examples |
| --- | --- | --- |
| 🟪 | **AI concept or technique**. An idea or method used when building with language models. | LLM, Prompt, System prompt, Prompt injection, Jailbreak, Guardrails, ... |
| 🟦 | **AI framework, library or tool**. Software you install or call to build, run or check AI features. | LangGraph, LangChain, LlamaIndex, LiteLLM, Docling, FastEmbed, ... |
| 🟩 | **AI data store or service**. A database or hosted service that holds or serves AI data and models. | Qdrant, pgvector, OpenRouter, Ollama, Google AI Studio, Hugging Face, ... |
| 🟧 | **AI model**. A trained model that generates text, makes embeddings or classifies input. | Qwen, gemini-embedding-001, Gemini, Gemma, Llama Guard, LFM, Nemotron, ... |

Anything **without** a marker is ordinary software (databases, web frameworks, build and delivery tools). Those are listed at the end of this page.

## 🟪 AI concept or techniques

An idea or method used when building with language models.

| Term | In plain words | Matters from | Read more |
| --- | --- | --- | --- |
| 🟪 **Agent** | A program where a model chooses which steps or tools to use to reach a goal, in a loop with hard limits. | V2 seed | [V2 record](v2-baseline/part-4-autonomy-protocols/10-agentic-assistant.md) |
| 🟪 **BM25** | A classic keyword-scoring method for search, the keyword half of hybrid search. | sub-stage 4.1 |  |
| 🟪 **Checkpointer** | Saves an agent's state so a paused run can resume later, even after a restart. | sub-stage 3.2 |  |
| 🟪 **Chunking** | Cutting documents into small pieces so each piece can be embedded and retrieved on its own. | V2 seed | [V2 record](v2-baseline/part-1-foundations/03-basic-rag.md) |
| 🟪 **Cosine similarity** | A score for how closely two embeddings point in the same direction; higher means more similar in meaning. | V2 seed | [V2 record](v2-baseline/part-1-foundations/03-basic-rag.md) |
| 🟪 **Embedding** | A list of numbers that captures the meaning of a text, so texts with similar meaning get similar numbers. | V2 seed | [V2 record](v2-baseline/part-1-foundations/03-basic-rag.md) |
| 🟪 **Evals** | Repeatable tests for an AI system: fixed questions with known right answers, scored by code or by a judge model. | sub-stage 0.7 | [stage guide](stages/00-foundation.md) |
| 🟪 **Golden set** | The fixed test questions, each with a known right answer, used to measure the system. | sub-stage 0.7 | [stage guide](stages/00-foundation.md) |
| 🟪 **Guardrails** | Checks around a model that block unsafe input or unsafe output. Ours start as simple rules. | V2 seed | [V2 record](v2-baseline/part-3-trust-safety/08-prompt-injection-guardrails.md) |
| 🟪 **Hallucination** | A confident answer that the facts or documents do not support. | V2 seed |  |
| 🟪 **HNSW** | An index that makes nearest-neighbour search fast on large collections by giving up a little exactness. | V2 seed |  |
| 🟪 **Human in the loop** | A person must approve a risky step, such as creating a task, before it happens. | V2 seed | [V2 record](v2-baseline/part-4-autonomy-protocols/10-agentic-assistant.md) |
| 🟪 **Hybrid search** | Combining meaning-based search (embeddings) with keyword search, which often finds more of the right documents than either alone. | sub-stage 4.1 |  |
| 🟪 **Inference** | Running a trained model to get an answer, as opposed to training it. | V2 seed |  |
| 🟪 **Jailbreak** | A prompt written to push a model past its safety rules. | V2 seed | [V2 record](v2-baseline/part-3-trust-safety/08-prompt-injection-guardrails.md) |
| 🟪 **LLM** | Large language model: a program trained on huge amounts of text that predicts likely next words, which lets it answer questions and write text. | V2 seed | [V2 record](v2-baseline/part-1-foundations/02-first-llm-chat.md) |
| 🟪 **LLM as judge** | Using a second model to grade another model's answers when code cannot score them. | V2 seed |  |
| 🟪 **LLM gateway** | One front door for calling many model providers the same way, with fallback and retries. | sub-stage 1.2 |  |
| 🟪 **MRR** | Mean reciprocal rank: how high the first correct result sits (rank 1 scores 1, rank 2 scores 0.5), averaged over all questions. | sub-stage 0.7 | [stage guide](stages/00-foundation.md) |
| 🟪 **Open-weights model** | A model whose trained numbers are published, so you can run it yourself. | V2 seed |  |
| 🟪 **OpenAI-compatible API** | An API shaped like OpenAI's chat API, which many providers copy, so one client can talk to all of them. | V2 seed |  |
| 🟪 **PII** | Personally identifiable information: data that identifies a person, such as a name or email address. | sub-stage 5.3 |  |
| 🟪 **Prompt** | The text sent to a model: instructions plus the question. What you put in it strongly shapes the answer. | V2 seed | [V2 record](v2-baseline/part-1-foundations/02-first-llm-chat.md) |
| 🟪 **Prompt injection** | Text that tries to trick a model into ignoring its rules, for example an instruction hidden in a document or a message. | V2 seed | [V2 record](v2-baseline/part-3-trust-safety/08-prompt-injection-guardrails.md) |
| 🟪 **RAG** | Retrieval-augmented generation: fetch relevant documents first and give them to the model, so its answer is based on your data and can cite sources. | V2 seed | [V2 record](v2-baseline/part-1-foundations/03-basic-rag.md) |
| 🟪 **recall@k** | Of the documents that should come back, the share found in the first k results. | sub-stage 0.7 | [stage guide](stages/00-foundation.md) |
| 🟪 **Reranker** | A second, more careful model that re-orders the first search results so the best ones come first. | sub-stage 4.1 |  |
| 🟪 **Retrieval** | Finding the pieces of text most relevant to a question before the model answers. | V2 seed | [V2 record](v2-baseline/part-2-grounded-intelligence/05-realistic-crm-rag.md) |
| 🟪 **Streaming** | Sending the model's answer word by word as it is produced, instead of waiting for the whole answer. Usually done with Server-Sent Events (SSE). | sub-stage 1.4 |  |
| 🟪 **Structured output** | Making the model answer in a fixed shape (JSON that matches a schema) instead of free text, so code can use it safely. | sub-stage 2.1 |  |
| 🟪 **System prompt** | Hidden instructions that set the model's role and rules before the user's message. | V2 seed | [V2 record](v2-baseline/part-3-trust-safety/08-prompt-injection-guardrails.md) |
| 🟪 **Tool calling** | The model asks the app to run a function, for example looking up a company, then uses the result in its answer. | V2 seed | [V2 record](v2-baseline/part-4-autonomy-protocols/09-tool-calling-mcp.md) |
| 🟪 **Vector database** | A database built to store embeddings and quickly find the nearest ones. Qdrant is ours. | V2 seed | [V2 record](v2-baseline/part-1-foundations/03-basic-rag.md) |
| 🟪 **Vector search** | Finding the stored texts whose embeddings are closest to the question's embedding. | V2 seed | [V2 record](v2-baseline/part-1-foundations/03-basic-rag.md) |

## 🟦 AI framework, library or tools

Software you install or call to build, run or check AI features.

| Term | In plain words | Matters from | Read more |
| --- | --- | --- | --- |
| 🟦 **Docling** | Reads PDFs, Word files and spreadsheets and turns them into clean text for chunking. | sub-stage 4.2 |  |
| 🟦 **FastEmbed** | Libraries that make embeddings on your own computer with open models, with no API key. | sub-stage 4.3 |  |
| 🟦 **Guardrails AI** | An open-source Python framework of validators that check a model's output. | later |  |
| 🟦 **LangChain** | A large toolkit of building blocks for model-based apps; LangGraph is built by the same team. | V2 seed |  |
| 🟦 **Langfuse** | Open-source tracing for model apps: it shows every model call and agent step with its cost and time. | sub-stage 5.1 |  |
| 🟦 **LangGraph** | A framework that models an agent's steps as a graph, with saved state and pauses for human approval. | sub-stage 3.2 |  |
| 🟦 **LiteLLM** | One interface to many model providers, with fallback, retries and rate-limit handling. | sub-stage 1.2 |  |
| 🟦 **LlamaIndex** | A toolkit focused on connecting models to your documents (retrieval and indexing). | sub-stage 4.1 |  |
| 🟦 **MCP** | Model Context Protocol: an open standard for exposing tools to models. FastMCP is the Python library for building such a tool server. | V2 seed | [V2 record](v2-baseline/part-4-autonomy-protocols/09-tool-calling-mcp.md) |
| 🟦 **NeMo Guardrails** | NVIDIA's open-source framework for rules around what a model may say or do. | sub-stage 5.3 |  |
| 🟦 **Presidio** | Microsoft's open-source tool that finds and masks personal data in text. | sub-stage 5.3 |  |
| 🟦 **promptfoo** | A tool that sends test questions to the running app and grades the answers. | V2 seed | [guide](../evals/README.md) |
| 🟦 **Pydantic AI / OpenAI Agents SDK** | Agent and structured-output libraries we only compare against, not adopt by default. | sub-stage 7 |  |
| 🟦 **Ragas / DeepEval** | Libraries that score answer quality (is it grounded in the sources, does it address the question). | sub-stage 5.2 |  |
| 🟦 **Spring AI** | Java-world counterparts of the Python AI frameworks, noted for the optional Spring Boot track. | later |  |

## 🟩 AI data store or services

A database or hosted service that holds or serves AI data and models.

| Term | In plain words | Matters from | Read more |
| --- | --- | --- | --- |
| 🟩 **Google AI Studio** | Google's service where you get a free key for Gemini models, including the embedding model we use. | V2 seed |  |
| 🟩 **Groq** | A hosted inference service with a free tier, one of the providers V3 may fall back to. | sub-stage 1.2 |  |
| 🟩 **Hugging Face** | The main hub for sharing open models and datasets. | sub-stage 4.3 |  |
| 🟩 **Ollama** | Ran a small open model on your own computer. V3 removed it in sub-stage 1.3 (cloud only). | V2 seed | [V2 record](v2-baseline/part-1-foundations/02-first-llm-chat.md) |
| 🟩 **OpenRouter** | A hosted gateway to many models, including free ones, behind one API key. | V2 seed | [V2 record](v2-baseline/part-2-grounded-intelligence/04-cloud-llm-provider.md) |
| 🟩 **pgvector** | A Postgres extension that stores embeddings inside Postgres. V2 used it first, then moved to Qdrant. | V2 seed |  |
| 🟩 **Qdrant** | The vector database we run. It stores each chunk's embedding and finds the closest ones to a question. | V2 seed | [V2 record](v2-baseline/part-1-foundations/03-basic-rag.md) |
| 🟩 **Together.ai** | A hosted inference service that gives free starting credits. | sub-stage 1.2 |  |

## 🟧 AI models

A trained model that generates text, makes embeddings or classifies input.

| Term | In plain words | Matters from | Read more |
| --- | --- | --- | --- |
| 🟧 **Gemini** | Google's family of models. We use its embedding model, gemini-embedding-001. | V2 seed |  |
| 🟧 **gemini-embedding-001** | Google's embedding model: turns text into 768 numbers. It makes every vector we store. | V2 seed |  |
| 🟧 **Gemma** | Google's family of open models, available on free tiers. | sub-stage 1.1 |  |
| 🟧 **LFM** | Liquid AI's small language models; one is our default free cloud model. | V2 seed |  |
| 🟧 **Llama Guard** | A model trained to classify whether a message is safe or unsafe. | sub-stage 5.3 |  |
| 🟧 **mxbai-embed-large** | An open embedding model V2 used locally before switching to Google's. | V2 seed |  |
| 🟧 **Nemotron** | NVIDIA's family of open models. | sub-stage 1.1 |  |
| 🟧 **Qwen** | An open model family from Alibaba. We ran the small 3-billion-parameter size locally in V2. | V2 seed |  |

## Ordinary software (not marked)

These are common in any enterprise application, not specific to AI:

- Web and API: React, Vite, TypeScript, FastAPI, Uvicorn, Spring Boot
- Data: PostgreSQL, asyncpg, Alembic, SQLAlchemy
- Build and run: Docker, Docker Compose, uv, npm, just
- Quality and delivery: GitHub Actions, ruff, mypy, ESLint, pytest, Vitest, Dependabot, Trivy, gitleaks, GHCR
- Operations: logging, request IDs, settings, health checks, OpenTelemetry

## Adding or changing a term

1. Edit [`ai-terms.yaml`](ai-terms.yaml): one entry per term, with a plain-words meaning.
2. Run `just ai-terms`. It re-marks every target doc and regenerates this page.
3. Commit the result. CI runs `just ai-terms-check` and fails if anything is out of date.
