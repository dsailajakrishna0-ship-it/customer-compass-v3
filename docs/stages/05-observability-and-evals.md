# Stage 5 — Observability and evals: see what the system did

> **Level:** beginner friendly; read [Stage 3](03-langgraph-port.md) for the 🟪agent steps this stage makes visible. **Reading time:** about 25 minutes so far (this guide grows with 5.4 and 5.5).
> **Status:** in progress. **5.1 (tracing), 5.2 (answer-quality 🟪evals), 5.3 (🟪guardrail comparison and 🟪PII) and 5.4 (🟪agentic retrieval) are done; 5.5 (manual versus framework) is in review.**
> **Roadmap:** [Stage 5](../roadmap.md#stage-5--observability-and-evals) · **Decisions:** [ADR 0022](../adr/0022-tracing-with-opentelemetry-and-langfuse.md), [ADR 0023](../adr/0023-judged-evals-with-deepeval.md), [ADR 0024](../adr/0024-guard-comparison-and-pii.md)

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](../ai-terms.md)

## In one minute

Until now the only record of a request was one log line and the audit tables. They say *what* was done and *whether it was allowed*. They do not say *why it was slow*, *which model really answered after a fallback*, *how many tokens a run used* or *which 🟪agent step failed*. A **trace** answers those.

| Shop idea | Project idea | In the code |
| --- | --- | --- |
| A receipt for one customer visit, listing every counter they stopped at | **A trace**: everything one request did | one trace per HTTP request, `app/middleware.py` |
| One line on the receipt (counter, minutes, what was bought) | **A span**: one timed step | `tracing.span()` in `app/tracing.py` |
| The counters are nested: "checkout" contains "scan item" | **Parent and child spans** | `agent.run` contains one span per step |
| The shop manager's screen that shows all receipts | **🟦Langfuse** | optional compose profile `observability` |
| A standard receipt format every till can print | **OpenTelemetry** | the same data could go to any other viewer |

## Concept 1 — Tracing (5.1)

**Trace, span, attributes.** A trace is the tree of spans for one request. A span has a name, a start and an end, a status, and **attributes**: small labelled facts such as `gen_ai.usage.input_tokens=69` or `retrieval.results=4`. The tree for one 🟪agent run looks like this:

![What one request records: the HTTP request span contains the model, retrieval, tool and agent spans](../img/diagrams/stage5-trace-map.png)

**Why OpenTelemetry and not the 🟦Langfuse library.** OpenTelemetry is the neutral standard: our code creates spans, and an *exporter* sends them wherever we choose. Langfuse accepts that format directly, so nothing in our code names Langfuse. Switching the viewer (or comparing it with another one in 5.5) is a setting, not a rewrite. Langfuse reads a few attribute names to decide how to draw a span (`langfuse.observation.type`: `generation` for a model call, `retriever`, `tool`, `agent`), and the `gen_ai.*` names for the model and token counts.

**The request id is the trace id.** Every request already has an id (1.1) that is in the log lines and the `X-Request-ID` header. When it is a 32-character hex id, the trace uses it as its trace id, so one id finds the logs *and* the trace. A caller's own free-form id cannot be a trace id, so that request gets a random trace id and the id stays an attribute.

**The privacy rule.** A trace store is a second place data can leak from, so spans carry **counts, names and sizes, never content**: tokens, milliseconds, how many results, which tool and the *names* of its arguments, not their values. Questions, answers, 🟪chunk text, tool arguments and results are only recorded when you set `TRACING_CAPTURE_CONTENT=true`, a second switch that is off by default. Attribute names that look like secrets are dropped, and an exception is recorded by its type only (its message could hold user text).

**It can never break a request.** Tracing is off by default (`TRACING_ENABLED=false`). When it is on, a broken exporter, an unreachable Langfuse or a failure while creating a span is logged once and the request carries on, the same rule as the 🟪reranker (ADR 0019). Exports are batched in the background, so a slow Langfuse does not slow the answer.

**The audit tables stay.** Traces are for *understanding* and expire; the audit tables are the *record*. The agent's own step list is still saved, and each step is also emitted as a span from the same place (`Trace.record`), so the two never disagree. One consequence: the audit trace marks "no company found" as an `error` step, so its span shows as an error too, even though it is a normal outcome for a question that names no company.

**Seeing it.** `docker compose --profile observability up -d` adds Langfuse (web, worker, Postgres, ClickHouse, MinIO, Redis) on `127.0.0.1:3000` only. The profile is optional because that is six more containers; the default stack is unchanged. See [testing guide 5.1](../testing-guide.md#stage-51-tracing-with-langfuse).

**Rule to remember.** *A trace is a receipt, not a copy of the conversation. Record how long and how many; record what only when someone chose to, and never let the recording break the thing being recorded.*

---

## Code tour: what changed in 5.1

| | Where | What |
| --- | --- | --- |
| 🟢 | `app/tracing.py` | Setup, the `span()` helper, the request-id trace id, attribute cleaning, the "never raise" rule |
| 🟡 | `app/middleware.py` | One span per request (not `/health`) |
| 🟡 | `app/llm/gateway.py` | A `generation` span per model call: model, tokens, latency, fallback |
| 🟡 | `app/rag/retrieve.py` | A `retriever` span: mode, results, similarity range |
| 🟡 | `app/routes/chat.py` | A `tool` span per executed 🟪tool call |
| 🟡 | `app/agent/trace.py`, `app/agent/workflow.py` | One span per 🟪agent step under `agent.run` and `agent.resume` |
| 🟡 | `app/config.py`, `app/main.py`, `.env.example` | `TRACING_*` and `LANGFUSE_*` settings; start and stop |
| 🟡 | `docker-compose.yml` | The optional `observability` profile |
| 🟢 | `tests/test_tracing.py`, `tests/agent_internals/test_agent_tracing.py` | 34 tests with an in-memory exporter, no 🟦Langfuse needed |

---

## Concept 2 — Judged evals (5.2)

Until now every 🟪eval was scored by code: was the right document ranked first, was the right tool called. Code cannot tell whether an *answer* is good. For that a second model, the **judge**, reads the answer and the passages it was built from.

| Shop idea | Project idea | In the code |
| --- | --- | --- |
| A mystery shopper with a checklist, not the till clerk marking their own work | **The 🟪judge model**, deliberately a different model from the one that wrote the answer | `JUDGE_MODEL` in `evals/judge.py` |
| The checklist itself | **The four metrics** | 🟦DeepEval's `FaithfulnessMetric`, `AnswerRelevancyMetric`, `ContextualPrecisionMetric`, `ContextualRecallMetric` |
| The shopper's signed score sheets, filed so an auditor can read them again | **The record-and-replay cache** | `evals/judged/cache.jsonl` |
| The report on the manager's desk each week | **The metrics table, one per branch** | `just eval-judged`, `just eval` |

**The four scores (0 to 1).** *Faithfulness*: every claim in the answer is backed by the 🟪retrieved text (this is the 🟪hallucination check). *Answer relevancy*: the answer addresses the question. *Context precision*: the useful passages were ranked above the useless ones. *Context recall*: the passages hold what a reference answer needs. DeepEval splits the answer into claims, asks the judge a yes/no question about each, and counts. The judge only answers questions; the arithmetic is code.

**Why a judged score can be trusted at all: pins.** A judge is a model, so it can change under you. Three things are pinned: the **🟪judge model**, the **🟪prompt version** (DeepEval writes the prompts, so its version is part of it) and the **questions with reference answers**. Change any of them and every cache key changes, so an old recording can never be mistaken for a new judgement, and a changed score between two branches means the *system* changed.

**Record once, replay for free.** Every judge call is looked up by `sha256(model, prompt version, prompt)`. In **replay** mode (the default, and the only mode CI uses) a missing key *stops the run*; there is no silent fallback to a live call. In **record** mode a missing key is sent to the free 🟩OpenRouter judge once and saved. The second run costs nothing, needs no key and gives identical numbers. CI therefore needs no secrets and cannot flake on a rate limit.

**Free tiers have a daily budget.** OpenRouter's free tier allows 50 requests a day. The first recording had one judge model refused all day (🟧Gemma, a shared upstream pool) and then ran out of daily requests after two cases, so the 🟪golden set holds the two recorded cases and three more wait in `golden/judged-pending.json`. The runner paces itself, stops at once on the daily limit, keeps what it has, and says "re-run to resume". Two cases are a smoke test of the plumbing, not a quality result.

**Why 🟦DeepEval and not 🟦Ragas.** Same metrics. Ragas declares 🟦LangChain, `langchain-community`, `datasets` and `tiktoken` as dependencies (I did not install it to measure); DeepEval takes any model through one small class (where our cache plugs in). Details and the other alternatives: [ADR 0023](../adr/0023-judged-evals-with-deepeval.md). 🟦promptfoo stays for prompt and adversarial checks, which is a different job.

**Kept out of the default install.** DeepEval brings about 80 packages and, inside `uv.lock`, moved `click`, `rich` and `huggingface-hub` for every install. So it lives in `evals/requirements-judge.txt` and `just eval-judged` layers it on for that one command; the API image and `uv sync` do not change.

**The table.** One per run, headed by the branch and commit:

```text
judged evals  branch feat/5.2-judged-evals @ 521c2c4  [replay]
judge nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free  prompts deepeval-4.3.4/json-v1  calls 14 (0 fresh)

metric                  baseline  this run    delta
faithfulness               1.000     1.000   +0.000
answer_relevancy           1.000     1.000   +0.000
context_precision          1.000     1.000   +0.000
context_recall             0.750     0.750   +0.000
```

The V2 retrieval numbers from `baseline/v2.json` are printed under it, and `just eval` now starts its table with the branch and commit too, so two branches' tables can be put side by side.

**Rule to remember.** *Pin the judge, record its answers, replay them everywhere else. A score you cannot reproduce is an opinion.*

---

## Code tour: what changed in 5.2

| | Where | What |
| --- | --- | --- |
| 🟢 | `evals/judge.py` | The pinned judge, cache key, record/replay, retry and daily-limit handling, reply parser, comparison, table |
| 🟢 | `evals/deepeval_adapter.py` | The only 🟦DeepEval import: a model class that sends 🟪prompts through the cache, plus the four metrics |
| 🟢 | `evals/run_judged.py` | The runner: records answers from `/chat/rag`, judges them, prints the table, writes the raw per-run JSON |
| 🟢 | `evals/golden/judged.json`, `judged-pending.json`, `judged/`, `baseline/judged-v1.json` | Cases with reference answers, recorded answers, the judge cache, the new baseline |
| 🟢 | `evals/requirements-judge.txt`, `justfile`, `.github/dependabot.yml`, `ci.yml` | The pinned library, `just eval-judged` and `-record`, a pip Dependabot entry, an offline replay step in CI |
| 🟡 | `evals/run_eval.py` | The table now starts with the branch and commit |
| 🟢 | `tests/test_judged_evals.py` | 25 offline tests: cache, replay, retries, parser, table, 🟪golden set (no keys, no DeepEval) |

---

## Concept 3 — Guardrails compared, and a PII guard (5.3)

**The question.** Stage 8 built a guard out of regular expressions: fast, free, predictable, and easy to fool. Before building more, measure it against the well-known alternatives, on a bigger and harder set than the one it was built on.

| Shop idea | Project idea | In the code |
| --- | --- | --- |
| A doorman with a list of known troublemakers' faces | **Rules**: patterns for known attack phrases | `app/guardrails/prompt_guard.py` |
| A second doorman who reads each visitor's intent and gives a thumbs up or down | **🟪LLM classifier**: a model answers SAFE or UNSAFE | `app/guardrails/llm_guard.py` |
| A security company with a rulebook for violence and theft, not for sweet-talkers | **🟧Llama Guard**: a safety classifier trained on harm categories | measured only |
| A security *system*: cameras, a rule engine, a control room | **🟦NeMo Guardrails**: a framework that runs rails, here one "self check input" rail | measured only |
| A shredder at the till for card numbers and ID numbers | **🟦Presidio**: finds personal data by pattern, checksum and a language model | optional, `PII_MODE` |

**How the comparison works.** 74 🟪prompts (44 attacks, 30 normal questions, many of which borrow attack words) and 32 🟪PII texts. Every strategy answers "flag or not" for each text. The table counts how many attacks each one flags (**detection rate**), how many normal questions it flags too (**false positives**) and how long it takes (**latency**). Hosted answers are recorded once in `evals/guards/cache.jsonl` and replayed everywhere else, so the table needs no keys and gives the same numbers every time: the same idea as the judge cache in 5.2.

```
just eval-guards          # replay: offline, free, no keys, checks every count against the baseline
just eval-guards-record   # record what is missing (needs OPENROUTER_API_KEY; about a cent)
```

**What came out** (details and caveats in [ADR 0024](../adr/0024-guard-comparison-and-pii.md)):

| Strategy | Attacks detected (of 44) | False positives (of 30) | Median latency |
| --- | --- | --- | --- |
| Our rules | 11 | 4 | 0.03 ms |
| Our LLM classifier | 25 | 3 | 1.2 s |
| Rules + classifier | 29 | 5 | 1.2 s |
| Llama Guard 4 | 10 | 0 | 0.9 s |
| NeMo Guardrails self-check | 43 | 16 | 0.9 s |

| PII strategy | Texts with PII found (of 20) | False positives (of 12 clean) | Median latency |
| --- | --- | --- | --- |
| Our rules | 0 | 0 | none |
| Presidio, default entities | 19 | 0 | 24 ms |
| Llama Guard 4 | 10 | 1 | 0.9 s |

**Three lessons.**

1. **Detection and false positives are one trade, not two numbers.** NeMo's rail catches 43 of 44 and also flags 16 of 30 ordinary questions. Llama Guard flags none of the ordinary questions and misses 34 of the 44 attacks. A guard that cries wolf gets switched off; one that never fires protects nothing. Look at both columns every time.
2. **A tool is a recipe, not a verdict.** The two model-backed rows share one small model. Rewording one policy prompt moved the same model from 27 false positives to 16. The honest reading is "this prompt on this model", and the table pins both.
3. **Match the tool to the threat.** Llama Guard is good at what it was trained for (harmful content) and wrong for "ignore your instructions". Presidio finds structured personal data that no list of attack phrases ever will. The rules are the only strategy that costs nothing and runs offline, which is why they stay the default.

**The 🟪PII guard.** Off by default. `PII_MODE=detect` flags card numbers, SSNs, IBANs, email addresses and phone numbers in the user's message (in the 🟪guardrail field and the audit log, as a type and a count, never the value); `redact` also replaces each with its type (`<CREDIT_CARD>`) before the rules, the classifier or the answering model see it. It needs Presidio and a small language model installed (not in the default image), and the API refuses to start if it is switched on without them. Names (`PERSON`) are off by default: a CRM is full of legitimate names.

**Rule to remember.** *Measure a guard on attacks and on ordinary questions at the same time, on a set it was not built on, and pin the model and the prompt. A detection rate without a false-positive rate is half a number.*

---

## Code tour: what changed in 5.3

| | Where | What |
| --- | --- | --- |
| 🟢 | `evals/guard_compare.py` | The strategies, the verdict cache (record and replay), the metrics, the table and the baseline check; no NeMo, 🟦Presidio or API imports |
| 🟢 | `evals/compare_guards.py` | The runner (replaces the 8.d script): `just eval-guards` and `just eval-guards-record` |
| 🟢 | `evals/golden/guards-extra.json`, `evals/guards/cache.jsonl`, `evals/baseline/guards-v1.json` | 44 more 🟪prompts, 32 🟪PII texts, the recorded verdicts, the pinned counts |
| 🟢 | `evals/requirements-guards.txt`, `justfile`, `.github/dependabot.yml`, `ci.yml` | Pinned 🟦NeMo Guardrails and Presidio outside `uv.lock`, the two recipes, a replay step in CI |
| 🟢 | `app/guardrails/pii.py` | The optional PII guard: lazy Presidio, `detect` and `redact`, never the value in the audit |
| 🟡 | `app/guardrails/llm_guard.py`, `app/config.py`, `app/main.py`, `.env.example` | `guard_input` runs the PII scan first when `PII_MODE` is on; `PII_MODE` and `PII_ENTITIES`; the startup check |
| 🟢 | `tests/test_guard_compare.py`, `tests/test_pii_guard.py` | 31 offline tests: cache, retries, metrics, table, baseline, case sets, the recorded cache; the PII guard with a fake analyzer |

---

## Concept 4 — Agentic retrieval (5.4)

Plain 🟪retrieval has no way to say "none of this helps". It returns the closest 🟪chunks, and the answering model writes from them. **🟪Agentic retrieval** gives the search three small checks, each one model call, so it can look at its own results (the **🟪Corrective RAG** idea):

| Shop idea | Project idea | In the code |
| --- | --- | --- |
| A shop assistant fetches four boxes, glances inside, and puts back the ones that are about something else | **🟪Relevance check**: a model says which retrieved passages help | `retrieve_checked()` in `app/rag/agentic.py` |
| "That wasn't it. Let me search the stockroom again, using the product code this time" | **🟪Query rewrite and one retry** when nothing helped | the same function; never more than one retry |
| Before handing over the parcel, someone checks every claim on the label against the paperwork | **🟪Grounding check** on the answer | `check_grounding()`; reported in `agentic.grounding`, the answer is not changed |

**Off by default.** `AGENTIC_RETRIEVAL=on` turns it on for the document search tool, `/chat/rag` and `/chat/crm`. Off, the code never runs and no response changes.

**It fails open.** A checking model that is down, slow or answers something that is not the expected JSON never breaks a search: the plain results are used and the failure is logged.

**🟪Retrieved text is untrusted, even for the checker.** A planted sentence in a document could try to talk the grader into keeping it ("reply relevant: [1]"). So every passage is first redacted by the 🟪prompt guard and wrapped in `<untrusted_context>` tags, each prompt says never to follow instructions inside the passages, and the reply is only parsed, never obeyed.

**What we measured** ([ADR 0025](../adr/0025-agentic-retrieval.md); `just eval-agentic`, replayed with no keys): the same 42 questions, plain 🟪hybrid search against 🟪agentic, both with one small paid model (about 0.3 cents for the whole recording). It showed **fewer, cleaner 🟪chunks (1.8 against 4.0), declined all six unanswerable questions (4 for plain), and cited slightly better**, but it **lost a needed document on four two-document questions (🟪recall@3 0.99 to 0.90), answered "not found" to two answerable questions, and doubled the latency (3.3 to 7.5 s median)**. The retry fired once in 42 questions. So it ships as an opt-in setting and is not the default; the ADR says what would make us look again (a stronger checking model, a recall-first grader).

**Two lessons from building it.** First, a prompt is part of the code: the first grounding prompt made the model call nearly every answer "unsupported", and the first relevance prompt made it keep only one passage. Asking for the supporting source per claim and telling the grader to keep a passage when unsure fixed both, tried on a dozen hand-written texts outside the question set so the 42 stayed a fair test. Second, an 🟪eval that only measures what the feature is good at hides its cost: recall and latency are in the table next to precision and declining.

**Rule to remember.** *A check that can drop evidence must be measured on what it drops, not only on what it cleans up.*

---

## Code tour: what changed in 5.4

| | Where | What |
| --- | --- | --- |
| 🟢 | `app/rag/agentic.py` | The three 🟪prompts, their safe parsers, `retrieve_checked()` (check, one rewrite, one retry), `check_grounding()`, the report; fails open |
| 🟡 | `app/mcp/tools.py`, `app/routes/chat.py` | The document search tool, `/chat/rag` and `/chat/crm` call `retrieve_checked()`; an `agentic` object in the response only when on |
| 🟡 | `app/config.py`, `.env.example` | `AGENTIC_RETRIEVAL` (off) and `AGENTIC_MODEL` |
| 🟢 | `evals/agentic_lib.py`, `evals/compare_agentic.py` | The record-and-replay cache of searches and model calls, the metrics, the table and the baseline check |
| 🟢 | `evals/agentic/cache.jsonl`, `evals/agentic/snapshots.json`, `evals/baseline/agentic-v1.json` | The recorded model calls and searches, and the pinned numbers |
| 🟡 | `justfile`, `.github/workflows/ci.yml` | `just eval-agentic` and `just eval-agentic-record`; a replay step in CI |
| 🟢 | `tests/test_agentic_retrieval.py`, `tests/test_agentic_compare.py` | 56 offline tests: the checks with a scripted model, the fail-open rule, the routes, the harness, the committed recordings replaying to the baseline |

---

## Concept 5 — Manual or framework? Measure each seam (5.5)

We build every piece by hand first so a guide can show what it does, and adopt a framework for a piece **only if measurements say it helps**. 5.5 runs that test on three pieces, each behind **one setting** (default `manual`, nothing changes unless you set it) and the **same function signature**, so the rest of the app cannot tell which side ran:

| Shop idea | Project idea | In the code |
| --- | --- | --- |
| Cutting a long roll of paper into sheets: every 600 millimetres, or at the nearest fold | **The chunker**: our fixed windows or 🟦LangChain's 🟪text splitter | `CHUNKER_IMPL`, `app/frameworks/chunker.py` |
| Fetching boxes from a warehouse with your own forklift routes, or the warehouse's own system | **🟪Retrieval**: our 🟩Qdrant query or LangChain's Qdrant store | `RETRIEVAL_IMPL`, `app/frameworks/retriever.py` |
| A clerk who follows a checklist (summary, history, documents), or a clerk who decides which files to pull | **The 🟪agent's evidence step**: our fixed graph or a 🟪prebuilt agent | `AGENT_IMPL`, `app/frameworks/agent.py` |

The framework packages are an **optional install** (`evals/requirements-frameworks.txt`): the default install and every default behaviour never need them. The framework side must keep what makes the app safe: the 🟪human-in-the-loop confirm gate, the audit log and the citations. The whole API-contract suite (26 tests) passes on both sides.

**What we measured** (`just eval-frameworks`, replayed with no keys; one ADR per seam):

| Seam | Result | Decision |
| --- | --- | --- |
| Chunker ([ADR 0026](../adr/0026-chunker-manual-or-langchain.md)) | The splitter never cuts a word in two (ours did on 6 of 33 🟪chunks) and 🟪recall@3 is 1.000 against 0.972: one question, on 33 chunks. A little more code (32 lines against 24). | **Manual stays the default**: the Java edition's chunk counts must match ours, and one question is a hint, not proof. |
| Retrieval ([ADR 0027](../adr/0027-retrieval-manual-or-langchain.md)) | The same chunks in the same order on all 42 questions, the same speed, 81 lines against 30, and it cannot search our keyword vector. | **Manual wins.** |
| Agent ([ADR 0028](../adr/0028-agent-manual-or-prebuilt.md)) | With one small model the prebuilt agent called no tool before its first answer on 12 of 13 runs, so valid citations fell from 14 of 14 to 8 of 13 and evidence per run halved. Same safety (no task written, the contract passes), 239 lines against 84. | **Manual wins**, and the ADR says what would change that. |

**Four lessons from building it.**
1. *A framework's helpful defaults can be silent bugs.* LangChain's retriever interface rescales a 🟪cosine score `c` to `(1 + c) / 2`, which would have turned our 0.45 relevance floor into "keep nearly everything". The code uses the store's raw-score search.
2. *Hidden calls.* Built with its defaults, the Qdrant store embeds a dummy text when it is created: a model call nobody asked for, made from inside the event loop where our async 🟪embedding cannot run.
3. *The contract suite earns its keep.* My first prebuilt agent put the raw request in its 🟪prompt; the test "an injection in the request never reaches the model" failed at once. A second failure showed that counting every model turn as a step made a revision cost 6 steps instead of 2.
4. *"The model decides" includes "decides not to".* Code that must always gather evidence should be code; a model choosing tools earns its place when the choice is genuinely open, such as which of several 🟪knowledge bases to search.

**Rule to remember.** *Adopt a framework for a piece when a measurement on your own questions says it helps, not when it is popular.* "Manual wins" is a valid, useful result.

**Not done.** The roadmap also asks for a small comparison of sending the same agent runs to 🟦Langfuse and to LangSmith. That needs a LangSmith account and key and has not been run.

---

## Code tour: what changed in 5.5

| | Where | What |
| --- | --- | --- |
| 🟢 | `app/frameworks/` (`chunker.py`, `retriever.py`, `agent.py`) | The 🟦LangChain and 🟦LangGraph side of each seam, behind the same function signature; imported only when its setting is on, with one clear error if the optional packages are missing |
| 🟡 | `app/config.py`, `.env.example` | `CHUNKER_IMPL`, `RETRIEVAL_IMPL`, `AGENT_IMPL` (default `manual`); `RETRIEVAL_IMPL=frameworks` with 🟪hybrid search is refused at start-up |
| 🟡 | `app/rag/chunking.py`, `app/rag/retrieve.py`, `app/rag/ingest.py`, `app/agent/workflow.py` | The dispatch on each setting; ingestion adds LangChain's nested `metadata` copy only when the framework retriever is on; the 🟪agent's `LlmCall` gained an optional `tools` argument |
| 🟢 | `evals/compare_frameworks.py`, `evals/frameworks/*.json`, `evals/baseline/frameworks-v1.json`, `evals/requirements-frameworks.txt` | The three tables, recorded and replayable, the baseline check, the pinned optional packages |
| 🟡 | `justfile`, `.github/workflows/ci.yml` | `just eval-frameworks`, `eval-frameworks-record`, `test-frameworks`; both run in CI |
| 🟢 | `tests/test_frameworks.py`, `tests/test_frameworks_compare.py`; `tests/contract/` | The framework side's tests (skipped without the packages), the harness tests, and the contract suite made side-aware |
