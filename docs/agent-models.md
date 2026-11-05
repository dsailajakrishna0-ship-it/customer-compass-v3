# Which kind of model each agent needs

One page to keep current. Every agent (and every other place the app calls a model) is listed with the **kind of model it needs** and why. Use it when choosing the default model, when ranking the fallback chain in `apps/api-py/models.yaml`, and when a new agent is added.

**Status, as of 2026-11-05.** Every call goes through one gateway (`generate()` in `app/llm/gateway.py`), and today **all agents use the same model**: the one picked in the web app, or the default and its fallback chain. The `role` the agents pass (`analyst`, `reviewer`, `task_drafter`) is accepted but not yet used to choose a model. The "needs" below come from reading each agent's prompt and parser, not from measurements; no evaluation with a real model has ranked them yet (the open item in the progress notes and in [ADR 0012](adr/0012-agent-limits.md)). Treat the "good fit" column as a recommendation, to be checked by the Stage 5 evals.

## The kinds of model

| Kind | What it is | Plain words |
| --- | --- | --- |
| **Chat model** (generation) | Reads text, writes text | Every agent below |
| **Instruction-following chat model** | A chat model that obeys a strict output format | The three agents, which must reply with JSON only |
| **Thinking (reasoning) model** | Writes out its reasoning before answering, which spends tokens | Good for judgement; risky under a small token cap (the empty-reply problem fixed in PR #48) |
| **Tool-calling model** | A chat model that can ask for a function call in the provider's native format | The Tool calling chat mode only; the three agents do not call tools themselves, code does |
| **Embedding model** | Turns text into numbers for similarity search | Document search; never writes text |
| **Classifier use of a chat model** | A chat model asked for one word (SAFE or UNSAFE) | The input guard |

## Today's agents and model calls

"Model type" uses the names from the table above. A call that needs **more than one type** says so.

| Agent or call | Model type | Job | Output the code expects | Needs | Good fit | Be careful |
| --- | --- | --- | --- | --- | --- | --- |
| **Analyst agent** (`run_analyst`) | **Chat model**, instruction-following (a thinking model also works) | Reads the evidence (E1, E2, ...) and proposes ONE next action with a short rationale and the evidence it cites | JSON: `action`, `rationale`, `evidence` list | Instruction following, honest use of only the given evidence, sound judgement, JSON-only replies | A mid-size or large instruction-tuned chat model; a thinking model is fine if the token cap leaves room | A tiny model invents facts or cites labels that do not exist. The code catches that (unknown labels force a revision), but each revision costs two more calls |
| **Reviewer agent** (`run_reviewer`) | **Chat model**, instruction-following, the strongest of the three (a thinking model suits it best) | Checks the proposal against the evidence: approve or send back with reasons | JSON: `verdict` (`approve` or `revise`), `reasons` | The strongest judgement in the chain, strict JSON, resistance to agreeing with everything | At least as capable as the Analyst's model, and ideally a **different model family** so the two do not share the same blind spots | The same model checking its own work tends to approve it |
| **Task Drafter agent** (`run_task_drafter`) | **Chat model**, small and fast, instruction-following | Turns the approved action into one task note of at most 200 characters | JSON: `task_note` (falls back to the action text if the reply is unusable) | Short, clean writing and basic instruction following | The **smallest and fastest** model you trust; this is the least demanding job | A thinking model wastes tokens here for no gain |
| **Input guard classifier** (`guard_input`, `GUARD_MODEL`) | **Chat model used as a classifier** | Answers SAFE or UNSAFE for the user's text | The first word of the reply; anything unclear counts as SAFE | Fast, cheap, consistent one-word answers | A small, quick chat model | Fails open on any error, so a flaky model weakens the guard silently. It is also an extra call on every agent run |
| **Document search** (the agent's third evidence step, and the `search_documents` tool) | **Embedding model** (no chat model) | Embeds the question, then finds the closest stored document chunks | A list of numbers per text; the nearest chunks come back from Qdrant | An embedding model | `gemini-embedding-001` today | Changing the embedding model means re-embedding every stored document (Stage 4.3) |
| **Document Q&A mode** (RAG) | **Two models: an embedding model, then a chat model** | Finds the chunks that match the question, then writes an answer from them with citations | Plain text with citations | Embeddings to find, a grounded chat model to answer | Embedding model as above, plus any decent instruction-tuned chat model | Answers over the token cap are cut off; free thinking models can run out of tokens |
| **Tool calling mode** | **Chat model with tool calling** (function calling) | Chooses which of the four tools to call and with what arguments, then writes the answer. One of the tools (`search_documents`) uses the embedding model inside | Native tool calls in the provider's format | A model whose provider supports function calling | A model OpenRouter lists as supporting tools | A model without tool support cannot take part; some models call a tool for every question |
| **General chat mode** | **Chat model** | Answers a question with the conversation so far | Plain text | A readable answer in 700 tokens | Any decent instruction-tuned chat model | Answers over the token cap are cut off |
| **CRM chat mode** | **Chat model** | Writes the answer from CRM facts that code has already fetched from the database | Plain text | A faithful, grounded answer | Any decent instruction-tuned chat model | It must not add facts that are not in the data it was given |

**There is no separate "RAG model".** RAG (retrieval-augmented generation) is a *pattern* that uses two ordinary models in turn: an embedding model to find the right text, then a chat model to answer from it. The same is true of "agent": an agent is code around one or more chat models, not a model type of its own.

## Model types the app does not use yet

| Type | What it does | Planned in | Notes |
| --- | --- | --- | --- |
| **Reranker** (cross-encoder) | Re-orders the retrieved chunks by how well each really answers the question | Stage 4.1 | A small model that scores a question and a chunk together; neither a chat nor an embedding model |
| **Judge model** | A chat model that scores answers in the evals | Stage 5.2 | Pinned to one model and prompt, so scores can be compared over time |
| **Safety classifier** (for example Llama Guard) | A model trained only to label text as safe or unsafe | Stage 5.3 | Compared with our rule-based and chat-model guards |
| **PII detector** (for example Presidio) | Finds names, emails and other personal data in text | Stage 5.3 | Mostly rules and small language models, not a chat model |
| **Document-layout models** (Docling) | Read page layout, tables and sheets in PDFs and spreadsheets | Stage 4.2 | Run inside the ingestion tool |
| **Multimodal, speech, image** | Understand images or audio, or produce them | Not planned | Listed so the gap is visible |

## What the free tier changes

All of the chat calls above currently use OpenRouter's `:free` models, which are rate-limited and change often. That is why the default chain exists, and why a small model is the default (`models.yaml`). For the **Reviewer** especially, the free tier is the weak point: when a better model is needed there, the choice is between a different free model and a small paid one. The gateway already allows a different model per call; what is missing is the setting that picks one per agent role.

## Adding a new agent (checklist)

Copy this table row for every new agent, in the same pull request as the agent:

| Field | Write |
| --- | --- |
| Agent and stage | name, the stage that adds it |
| Job in one sentence | what it decides or writes |
| Output the code expects | the exact format (JSON keys, one word, free text) and what happens when the reply is wrong |
| Needs | instruction following, tool calling, long context, reasoning, speed, cost |
| Good fit | the kind of model, not a model name (names go stale; they belong in `models.yaml`) |
| Be careful | the failure mode you have seen or expect |
| Measured by | the eval case that checks it (Stage 5), or "not measured yet" |

Planned agents from the roadmap: **Stage 7** adds a planning agent and a supervisor that chooses between specialists. A supervisor is the most demanding role of all (routing decisions, strict format, resistance to being steered by text inside the evidence), so it should get the strongest model, not the cheapest.

## Related

- [agent-boundaries.md](agent-boundaries.md): which pattern for which question.
- [ADR 0009](adr/0009-litellm-gateway.md) (the gateway), [ADR 0010](adr/0010-cloud-only-models.md) (cloud-only), [ADR 0012](adr/0012-agent-limits.md) (limits, and the measurements still to take).
- `apps/api-py/models.yaml`: the default, the fallback chain and the last-known-good list.
