# 0025 — Agentic retrieval: a relevance check, one corrective retry and a grounding check, optional and off

- **Status:** Accepted (ships as an opt-in setting; **not** recommended as a default)
- **Date:** 2026-11-13
- **Roadmap sub-stage:** 5.4

## Context

Plain retrieval returns whatever is closest, even when none of it helps, and the answer model then writes from weak evidence. The roadmap asks whether the document search should look at its own results: a **relevance check** on the retrieved passages, a **query rewrite with one retry** when they are weak (the Corrective RAG idea), and a **grounding check** on the answer. It must be behind a setting and off by default, measured on the same questions as plain hybrid search, and it ships only if quality improves at acceptable latency and cost; otherwise this record says why not.

## Decision

1. **Build it by hand, in one module** (`app/rag/agentic.py`), following the framework policy: three small prompts, three safe parsers, no framework. A framework version is for 5.5 to compare.
2. **`AGENTIC_RETRIEVAL=off|on`, default `off`**, and `AGENTIC_MODEL` (the default chat model when unset) for the checking calls. Off, nothing runs and no response changes. On, it wraps the search used by the document search tool (`search_documents`), `POST /chat/rag` and `POST /chat/crm`; those two chat routes then add an `agentic` object to the response (what was retrieved, kept and rewritten, calls, tokens, the grounding verdict).
3. **The relevance check keeps passages, it does not rank them.** One call: the question and the numbered passages in, `{"relevant": [...]}` out. If nothing helps, **one** rewrite call and **one** more search (never a second retry); the new passages are checked the same way and merged after the first ones, without duplicates. If still nothing helps, nothing is returned, and the route says it found nothing (the honest answer).
4. **The grounding check reports, it does not rewrite.** One call after the answer: the model splits the answer into claims and names the sources that state each; a claim with no source is "unsupported". The result is `agentic.grounding` in the response. An answer that only says the sources lack something has no claims and skips the call.
5. **Every check fails open.** If a model is unreachable, slow or answers something that is not the expected JSON, the plain search results are used and the failure is logged. A check can make a search worse only by judging badly, never by breaking it.
6. **Retrieved text stays untrusted.** Before a checking model sees a passage it goes through the prompt guard (known injection phrases redacted) and is wrapped in `<untrusted_context>` tags, and each prompt says never to follow instructions inside the passages. The reply is only parsed. The 5.3 guard and audit on the chat routes are unchanged and still scan what reaches the answering model.
7. **One replayable table**, the way 5.2 and 5.3 did it: `just eval-agentic` replays the recorded searches (`evals/agentic/snapshots.json`) and model calls (`evals/agentic/cache.jsonl`) with no keys and no network, and CI runs it. `just eval-agentic-record` records what is missing (needs the stack, `GOOGLE_API_KEY` and `OPENROUTER_API_KEY`).

## Results

Measured 2026-11-13 on the 42 retrieval questions (36 answerable, 6 not), hybrid search, 4 chunks to the answering model. **Every model-backed step in both arms (checks and answers) uses `meta-llama/llama-3.1-8b-instruct`** (US$0.02 per million input tokens, US$0.04 per million output tokens, from OpenRouter's model list the same day), because the free models allow 50 requests a day in total and this needs several hundred calls. The recording cost about **US$0.003** in all, including a first run with the v1 prompts (below).

| | plain hybrid | agentic |
| --- | --- | --- |
| recall@1 (answerable) | 0.787 | 0.801 |
| recall@3 (= recall@4, all chunks shown) | 0.986 | 0.903 |
| MRR | 0.958 | 0.958 |
| citation correctness (cited chunks from a relevant document) | 0.897 | 0.919 |
| answerable questions answered | 36 of 36 | 34 of 36 |
| unanswerable questions declined | 4 of 6 | 6 of 6 |
| answers the grounding check passed | 39 of 42 | 38 of 41 |
| chunks shown per question | 3.95 | 1.81 |
| median / p95 ms per question | 3319 / 4797 | 7467 / 13785 |
| model calls per question (answer included) | 1.00 | 2.88 |
| tokens in / out | 24,619 / 1,502 | 56,202 / 3,872 |
| cost for the 42 questions | US$0.0006 | US$0.0013 |
| queries rewritten | 0 | 1 |

What the numbers say:

- **It is more precise and it declines better.** It shows fewer, cleaner chunks (1.81 against 3.95), declines all six unanswerable questions (two of the four plain answers that did not decline were invented: "Who is the CEO of Vertex Analytics?" and "How many employees does Acme Fabrication have?"), and its citations are slightly more often right.
- **It loses recall.** On four questions that need two documents (`ret-02`, `ret-04`, `ret-18`, `ret-22`) the relevance check kept only one, and on `ret-17` it dropped the only relevant passage, so two answerable questions were answered "not found" (34 of 36). Recall@3 falls 0.986 to 0.903. Plain hybrid search already puts the right documents in its top four (0.986), so there was little for a check to rescue; the check's cost here is the passages it wrongly drops.
- **The rewrite hardly mattered.** One query in 42 was rewritten (the weather question), and it found nothing. With a good first search, "retry when weak" rarely fires.
- **Latency doubles and calls triple** (3.3 to 7.5 s median, 4.8 to 13.8 s at p95; one call becomes about three) for a cost that is still tiny in money, because the checking model is small. The latency, not the money, is what a user feels.
- **The grounding check works as a flag.** With the v2 prompt it passes the answers that restate their sources and flags invented ones (it flagged the two invented plain answers above, and three agentic answers). It has not been checked against human judgement beyond a few hand-written texts and a read of the flagged answers, so treat it as a signal, not a verdict.

**v1 prompts, kept as history.** The first prompts gave worse results: the grounding check said "unsupported" for almost every answer (3 of 42 and 0 of 41 passed, because the model listed ordinary restated claims), and the relevance check kept only the first passage most of the time (recall@3 0.903, 1.31 chunks shown). Both are prompt faults, not a limit of the idea. The v2 prompts ask for the supporting source per claim, tell the grader to keep a passage when unsure and when an answer needs two documents, and skip refusals. They were tried on a dozen hand-written texts that are not in the question set, not tuned on the 42 questions; the 42 were then recorded once with them.

## Decision on shipping

**Ship the code as an opt-in setting and leave it off.** It does not meet the roadmap's bar for becoming the default: quality is mixed (precision and declining up, recall down), latency doubles, and a checking model that is a small, cheap one drops needed passages. It is useful for one thing the baseline could not do, declining questions the documents do not answer, and it is the first place the grounding flag exists. The default stays plain hybrid search.

**What would make us look again:** a stronger checking model (set `AGENTIC_MODEL`) that keeps both documents on the two-document questions, measured with `just eval-agentic-record`; or a corpus where first-search quality is worse than here (the baseline is already near its ceiling: MRR 0.96, recall@4 0.99). Making the relevance check recall-first (drop a passage only when it is plainly about another customer) is the first change to try.

## Alternatives considered

- **A framework implementation** (LangGraph prebuilt corrective-RAG graph, LlamaIndex or LangChain retrievers): left to 5.5, which compares them against this hand-written version on the same table.
- **Reranking instead of grading** ([ADR 0019](0019-hybrid-search-and-reranker.md)): a reranker orders the candidates; it never says "none of these help", so it cannot decline or trigger a retry. The two are complementary and can be combined; the comparison here is against plain hybrid search only, as the roadmap says.
- **Grade by similarity score** (a higher floor than the current 0.45): free and fast but blind to meaning; the baseline notes that plausible-but-uncovered questions score in the same range as real matches.
- **Rewrite the answer when it is ungrounded:** rejected for now; the check reports, a person decides, the same rule as the guard (flag, do not silently change text).

## Consequences

- With the setting on, a chat request makes about two extra short model calls and takes about twice as long; the response gains an `agentic` object (only then). The Java edition is not changed by this stage; it can port the layer later behind the same setting.
- The comparison files are committed: about 80 KB of recorded calls and 160 KB of recorded searches over synthetic documents. A change to a prompt, to the pinned model or to the sample documents invalidates the recordings; the replay check in CI then fails with a missing-recording message, which is the signal to re-record.
- The 5.2 DeepEval judge was **not** run on the agentic answers: the free judge allows 50 requests a day, which the 5.2 recordings already used. Answer quality here is measured by recall, citation correctness, declining and the grounding check, not by the faithfulness and relevancy scores. Extending `just eval-judged` to a second answer set is the follow-up.
