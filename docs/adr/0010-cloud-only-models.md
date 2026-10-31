# 0010 — Cloud-only chat models

- **Status:** Accepted
- **Date:** 2026-11-01
- **Roadmap sub-stage:** 1.3

## Context

V2 could answer with a small model run on the local computer (Ollama, `qwen2.5:3b`) as well as with hosted OpenRouter models, and the web app had a dropdown to switch. [ADR 0001](0001-v3-goals-and-tooling-rule.md) already set the V3 direction (cloud models only, free tiers only), and the gateway from [ADR 0009](0009-litellm-gateway.md) absorbs what made the local model attractive as a safety net: rate limits and outages.

Keeping the local path would mean two code paths to test, document and keep working, a multi-gigabyte model cache and an extra container for everyone, and answers from a model small enough to produce terse replies, odd citation placement and the occasional near-empty answer.

## Decision

Remove the local model runner and the idea of a "provider" completely, not only the container.

- **Infrastructure:** the `ollama` Compose service and its volume, the cache-reuse script, the `OLLAMA_*`, `LLM_PROVIDER` and `GUARD_PROVIDER` settings, and the CI smoke test's dependency on it.
- **Gateway:** one kind of route, hosted models through OpenRouter. With no `OPENROUTER_API_KEY` there is no chain, and `generate()` raises one clear error that says to set the key (the API returns it as a 503).
- **API (a deliberate contract change; the web app is the only consumer):** requests no longer take `provider` (an old one is ignored), and responses and `usage` no longer carry `provider` or `fallbackFrom`. `usage.fallbackFromModel` says which model failed first.
- **Web app:** the provider dropdown, its state and its stored value are gone; the model dropdown is always shown.
- **Classifier guard and evals:** the optional classifier uses the default model (`GUARD_MODEL` overrides it); the promptfoo judge is a free OpenRouter model.
- **Baseline comparability:** the saved V2 baseline's `tools` and `agent` scores came from the local model, so they are **not comparable** with a hosted model. `run_eval.py` now compares the chat model recorded in the baseline with the current one and, if they differ, skips those two suites and says why, instead of reporting a false regression. Retrieval and the guard do not depend on the chat model and stay comparable.
- **Keeping it out:** `tests/test_no_local_models.py` fails if the word reappears in any tracked file outside a short allowlist of places that exist to discuss it (decision records, the frozen V2 record, the plan, the stack record, the Stage 1 guide, the saved V2 baseline and the code that recognises it).

## Alternatives considered

- **Keep it as an optional Compose profile:** two paths to maintain and explain for a feature the plan removes. The gateway makes re-adding it cheap if ever wanted (one more route in `build_chain()`).
- **Remove only the container but keep the provider switch:** leaves a dead concept in the API, UI and docs.
- **Keep the `provider` field in responses as a constant:** harmless, but it would keep suggesting a choice that no longer exists.

## Consequences

- **Chat needs internet and a free OpenRouter key.** There is no offline development of the chat path; tests and CI are unaffected (they use a scripted fake provider).
- **Privacy:** prompts, retrieved text and CRM facts now go to OpenRouter and the model providers behind it. This is acceptable only because every record in this repository is synthetic; real data would need a different decision.
- **Less predictable answers:** free models rotate, so the same question can be answered by different models over time.
- **The tool-call and agent baselines must be re-taken with a hosted model.** Until then `just eval` checks retrieval and the guard only. Taking the new baseline needs an OpenRouter key and also gives the data to rank the provisional `fallback_chain`.
- **Untested here:** the promptfoo judge configuration (`openrouter:...`), the guard classifier and the whole chat path on real OpenRouter models, because no key was available.
- Existing browsers keep an unused stored value (`customer-compass:provider`), which is ignored.
