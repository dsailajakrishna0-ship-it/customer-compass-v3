# 0023 — Judged answer-quality evals with DeepEval, a pinned judge and a replay cache

- **Status:** Accepted
- **Date:** 2026-11-13
- **Roadmap sub-stage:** 5.2

## Context

The V2 evals measure things code can check: did retrieval rank the right document, did the right tool get called, did the guard block the prompt. None of them says whether the *answer* is good: is every claim supported by the retrieved text (faithfulness), does it address the question (relevancy), were the useful passages ranked first (context precision), was anything needed missing (context recall). That needs a second model to read the answer, a *judge*. The roadmap asks for Ragas or DeepEval next to promptfoo, with a pinned judge model, and a metrics table per branch.

Constraints: free tiers only ([ADR 0010](0010-cloud-only-models.md)); the free OpenRouter models are rate limited and come and go; CI must never use keys or the network; the default install and the API image must stay light; the owner must be able to compare branches and trust that a changed number means a changed system, not a changed judge.

## Decision

**Library: DeepEval 4.3.4 (Apache-2.0, Python 3.10+).** It has the four metrics above ready-made, each with the judge prompts built in, and takes any model through one small class (`DeepEvalBaseLLM`), which is where our cache goes. Checked on PyPI on 2026-11-13.

**Judge: one pinned hosted model**, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` on OpenRouter (`evals/judge.py`), deliberately not the model that writes the answers (`liquid/lfm-2.5-2.6b:free`, the default in `models.yaml`). The first choice, Gemma 4 31B, answered HTTP 429 from a shared upstream pool for a whole day, so the pin moved; this is the reason the pin lives in one constant with a date and why the cache key includes it.

**Pinned prompt version.** DeepEval writes the prompts, so `JUDGE_PROMPT_VERSION` is `deepeval-<version>/json-v1`. A DeepEval upgrade changes the prompts, so the version string must change with it and the cache is re-recorded on purpose.

**Record and replay.** Every judge call is keyed by `sha256(model, prompt version, prompt)`.
- `replay` (the default, and the only mode CI may use): never touches the network. A missing key stops the run (`ReplayMiss`); it never silently falls back to a live call.
- `record`: a missing key is sent to OpenRouter once (paced to stay under the free tier, retries on 429/5xx, gives up cleanly and keeps what it has), then saved. A second run costs nothing and gives identical numbers.
- The cache (`evals/judged/cache.jsonl`) holds sha256 hashes and raw replies, not prompts (prompts contain answer text). Each run also writes every prompt and raw reply to `evals/runs/judged-<time>-<sha>.json` (git-ignored).
- The answers being judged are recorded the same way (`evals/judged/subjects.json`, taken from `POST /api/v1/chat/rag`), so replay needs no stack.

**One table per run.** `just eval-judged` prints branch and commit, judge and prompt version, call counts (fresh vs cached), the four scores next to `evals/baseline/judged-v1.json`, and the V2 retrieval numbers from `evals/baseline/v2.json` underneath. `evals/baseline/v2.json` is untouched; `judged-v1.json` is a new baseline, written only with `--save-baseline`.

**Small on purpose.** Questions from the retrieval golden set with hand-written reference answers (`golden/judged.json`). With explanations switched off a case costs 7 judge calls (measured), plus one call to the chat model for the answer. OpenRouter's free tier allows **50 requests a day** (checked 2026-11-13, `X-RateLimit-Limit`); the first recording used that up after two cases, so `judged.json` holds the **2 cases recorded** and three more, already written, wait in `golden/judged-pending.json` until a later day (or credits) lets them be recorded. The runner stops at once on the daily limit instead of retrying, and keeps what it has.

**promptfoo stays** for prompt and adversarial checks (`evals/*.promptfooconfig.yaml`): it compares prompts and runs red-team style inputs, which is a different job from scoring answers.

**Kept out of the default install.** DeepEval brings about 80 packages (grpcio, a telemetry client, pytest plugins) and, when put in `uv.lock`, it moved `click`, `rich` and `huggingface-hub` down for *every* install because uv resolves groups together. So it is pinned in `evals/requirements-judge.txt` and layered on only by `just eval-judged*` (`uv run --with-requirements`). Its telemetry is switched off (`DEEPEVAL_TELEMETRY_OPT_OUT`) before it is imported.

## Alternatives considered

- **Ragas 0.4.3 (Apache-2.0).** Same metrics, and the best-known names for them. Rejected: it declares LangChain, `langchain-community`, `datasets` and `tiktoken` as dependencies (from its PyPI metadata; not installed or measured here), whereas DeepEval has no LangChain, and we use LangGraph (not LangChain) only in the optional 5.5 comparison. DeepEval's metrics are the same ideas with the same inputs, so switching later would change the numbers, not the design (judge, cache and table are library-neutral).
- **promptfoo's `llm-rubric` as the only judge.** Rejected as the main tool: it grades pass/fail against a rubric you write, not the four standard 0 to 1 scores, and it needs Node. Kept for what it is good at.
- **A hand-written judge.** Fully ours and tiny, but we would be maintaining prompts that the libraries already test.
- **Putting DeepEval in the lock file** as a group. Rejected, see above.
- **No cache, live judge in CI.** Rejected: rate limits, keys in CI, non-determinism.

## Consequences

- Two cases are a smoke test, not a quality measurement: all three of faithfulness, relevancy and precision came out at 1.0 and recall at 0.75. Use the table to see that the plumbing works and to compare branches once the pending cases are added.
- Scores from a small free judge are noisy. The check tolerance is wide (±0.15) and the table is for comparing branches, not for absolute quality claims.
- Changing the judge, the prompt version or the cases means re-recording (`just eval-judged-record`, needs `OPENROUTER_API_KEY` and a running API for new answers) and saving a new baseline on purpose.
- A free model can vanish. The pin then fails loudly in `record` mode; `replay` keeps working on the recording.
- `pip-audit` and Dependabot's `uv` ecosystem do not see `evals/requirements-judge.txt`; a `pip` Dependabot entry covers it, and a bump that changes DeepEval's prompts will fail the replay check, which is the signal to re-record.
- The Java edition has no equivalent yet; the judged runner reads only the HTTP contract, so it can be pointed at the Java API later.
