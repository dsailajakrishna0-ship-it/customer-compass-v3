# Agent boundaries — which pattern for which question

Use the simplest pattern that answers correctly. More autonomy costs more time,
more tokens and more risk.

| Pattern | Use when | Example in this repo | Cost / risk |
| --- | --- | --- | --- |
| **Direct SQL / CRM facts** | The answer is a known field or count | "What is Acme's industry?" (Stage 5 CRM mode) | Fastest, exact |
| **Direct RAG** | The answer lives in documents | "What does the alerting guide say?" (Stage 3 RAG mode) | One retrieval + one LLM call |
| **Tool calling (Stage 9)** | One reactive lookup or one action; the model picks one tool | "What open deals does Acme have?" | 1–2 LLM calls; mutating tools need confirmation |
| **Deterministic workflow** | The step sequence is known in advance | Stage 10 evidence gathering (summary → interactions → documents) | Predictable, testable, no LLM choice |
| **Code-controlled multi-agent (Stage 10)** | A judgement task benefits from separate roles and a check | Analyst → Reviewer → Task Drafter | ~3+ LLM calls (~80 s locally); hard limits needed |
| **Agent that picks its own tools/steps (V3)** | The sequence cannot be known in advance | Not built in V2 | Highest risk; needs a framework, limits and evaluation |

## Rules that apply to every row

- Writes need explicit user confirmation, and the write path is separate from the read path.
- Bound steps, time and retries; surface evidence and a trace.
- Guard untrusted text (user input, documents, interactions) with the Stage 8 guards.
- Do not re-implement retrieval, authorization or task creation inside an agent; reuse Stage 5 and Stage 9 code.
- Do not use agents when a simpler row answers the question. `needs_agent` in `agent/policies.py` routes simple questions to `direct`.
