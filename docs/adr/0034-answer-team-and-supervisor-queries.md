# 0034: an answer team and supervisor-written search words

- **Status:** Accepted
- **Date:** 2026-11-14
- **Roadmap sub-stage:** E3.2 (Python extension; the twin of the Java edition's E3.2, its ADR 0021)

## Context

E3.1's supervisor ([ADR 0033](0033-supervisor-with-specialist-agents.md)) could only reorder two optional steps of one workflow (the account follow-up), and a plain question got `route: "direct"` with a hint to use the chat modes. Two things were left for this slice: a specialist that **answers a question**, and a decision with real content for the supervisor.

## Decision

- **Two kinds of request, two teams, one supervisor.** `POST /agent/supervise` no longer redirects a plain question. The keyword rule that already separates a follow-up from a simple question (`needs_agent`) now picks the team **in code** (`mode_of`, recorded in the state as `mode`). A follow-up runs the E3.1 team and ends at the approval gate. A plain question runs the **answer team** (`crm_facts`, `researcher`, `answerer`) and ends with an answer: no proposed task, no gate. The supervisor's prompt tells it which kind of request it is handling. The gate never depends on a model's choice.
- **The answerer** is a new specialist (one model call, fixed prompt, role `answerer`). It sees the guarded question and the labelled evidence (the CRM facts when a customer was named, plus the knowledge-base chunks the researcher found, wrapped as untrusted context) and cites labels like `[E2]`. **A code rule fails closed:** an answer that cites no label that exists is replaced by the fixed text "I could not find this in the CRM facts or the knowledge bases." and the response says `"grounded": false`. The output guard then scans what will be shown (leaked prompt text, another customer's name when a customer was named) and detections go to the security audit log under the `agent` endpoint, like the account agent's.
- **No customer is fine for a question.** `crm_facts` still identifies a customer when one is named; a missing one does not stop a question (it still ends a follow-up, as in E3.1).
- **The supervisor writes its own search words.** When it chooses the researcher it may add a `query` to its JSON; the researcher searches with those words instead of the request. The query is model-written text used as a search string: trimmed, whitespace collapsed, capped at 200 characters, honoured only when the choice is the researcher, recorded on the turn (`query`), and the chunks it retrieves pass through the same guard as always. This applies to both teams.
- **The supervisor still chooses only from an allowed list.** For a question: the researcher first (one allowed choice, so no model call), then the answerer, with the researcher also allowed once more (a real choice, so the supervisor is asked): "search again with different words, or answer now". The researcher can run at most twice. An unreadable or disallowed answer falls back to the answerer.
- **Response shape for a question:** `route`, `status` (`answered`), `trace`, `message`, `grounded`, `evidence`, `citations` (the evidence items the answer cited), `guardrail`, `llmCalls`, `supervisor`. No `company` and no `proposedTask`.
- **Not done: parallel specialists.** Running the CRM facts and the researcher at once needs a reducer for the evidence list; the work each does is short, so the gain would only be latency.

## Differences from the Java edition

- Same rules, response shape and team choice. The answerer here is shown the question after the input guard (`neutralized_text`), the same value the chat routes use; the Java answerer is shown the raw request. Detections on the question are reported in the response's `guardrail` here (the account agent's report already included them).
- The graph is compiled once here (the run's context travels in the LangGraph config) and per run in Java, as in E3.1.

## Alternatives considered

- **Let the supervisor choose the team too** (a "task or question?" decision): more autonomy, but a wrong first choice sends a follow-up request down a path with no approval gate. The gate must not depend on a model's mood.
- **Reuse the multi-source chat route (`/chat/multi`) as the answerer's tool:** the answer team would be a thin wrapper, and the supervisor would decide nothing about retrieval.
- **No code rule on citations:** simplest, and a small model then answers confidently from nothing. The fixed text is the safety net, the same idea as the reviewer's rule for recommendations.

## Consequences

- A plain question to `/agent/supervise` now gets an answer. The chat modes are still the better route for a quick question (one model call); the supervisor adds a decision and a research step.
- A question costs one supervisor call (the second-visit choice) and one answerer call, plus nothing for the other turns.
- `supervisor.turns` shows the model's search words on the turn where it chose them.
- Not measured: how a real small model behaves as the answer-team supervisor, whether its own search words help, and how often it cites correctly. That is for E3.3.
