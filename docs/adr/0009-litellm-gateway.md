# 0009 — The model gateway (LiteLLM)

- **Status:** Accepted
- **Date:** 2026-10-31
- **Roadmap sub-stage:** 1.2

## Context

V2 called models with three hand-written modules (`provider.py`, `cloud.py`, `ollama.py`) and a single rule: if the requested provider failed, try the other provider once. On a free tier that is too blunt. A rate limit (HTTP 429) on one free model threw away the whole cloud provider and fell back to a small local model, nothing waited or retried, a failing model was hammered again on the next request, and every provider quirk (token fields, errors, cost) was parsed by our own code.

## Decision

Use **LiteLLM 1.106.6** (MIT, pinned by `uv.lock`) through its `Router`, behind one function, `generate()` in `app/llm/gateway.py`, which keeps the old signature so callers only change an import.

- **Ordered chain.** The requested model first (the default if none is named), then the models in `fallback_chain` in `models.yaml`, then the other provider, for parity with V2. Ollama remains a route until sub-stage 1.3.
- **Failures are told apart.**
  - **429:** no retry on the same model; move to the next at once (retrying a rate-limited free model immediately only wastes time).
  - **Timeout or 5xx:** retry the same model (default 2 retries) with growing waits, then move on.
  - **Anything else** (bad request, authentication): no retry; move on.
- **Cool-down.** A model that just failed is skipped for 30 s, so the next requests do not hit it. A 429 benches it at once; a timeout or 5xx only after its retries ran out (per-error-type limits).
- **One result shape.** `GenerationResult` gains `fallback_from_model`. The API's `usage` gains `fallbackFromModel`; the web note names both models for a model-to-model fallback.
- **One safe error.** If every model fails, `LlmUnavailableError` lists the models tried and the last error type, never keys or provider messages. Empty answers are still an error, as in V2.
- **Settings:** `LLM_TIMEOUT_SECONDS` (60), `LLM_MAX_RETRIES` (2), `LLM_RETRY_MIN_SECONDS` (1), `LLM_COOLDOWN_SECONDS` (30).
- **Tests use LiteLLM's custom-provider hook** to script exact outcomes (a 429, a 500, a timeout, then success), so nothing touches a network or a key.

### LiteLLM defaults we turned off, and why

| Default | Why we changed it |
| --- | --- |
| In its default "DEV" mode, `import litellm` **loads the nearest `.env` file up the directory tree into the process environment** | It bypassed `config.py` (ADR 0008) and pulled a developer's real secrets into tests: a test that should have skipped ran because the repo-root `.env` had a Google key. `LITELLM_MODE=PRODUCTION` is set in `config.py`, and a test pins it in a fresh interpreter. |
| It downloads its price list from GitHub on every import | A network call at start-up and prices that change by the day. `LITELLM_LOCAL_MODEL_COST_MAP=True` uses the copy bundled with the package. |
| Its logs report a normal fallback at ERROR level and can include message content | Its loggers are silenced and message logging is off; our own gateway logs one line per failed attempt (model, error type, status) with the request id, and never prompts or keys. |

### A dependency override

LiteLLM declares `filelock<4.0`, and `pip-audit` reports 13 advisories in `filelock` 3.32.7, all fixed only in 4.x (they concern local file-lock edge cases such as symlink races). We only reach `filelock` through `huggingface-hub`'s download cache and LiteLLM's proxy command line, neither of which we run, so exposure is very low, but CI would fail and suppressing 13 IDs would hide future ones. `pyproject.toml` therefore overrides `filelock>=4.2.1` (4.2.4 is installed); the suite passes with it. **Remove the override once LiteLLM raises its cap.**

## Alternatives considered

- **Keep the hand-written code and add a fallback loop:** fewer packages, but it keeps the plumbing V3 exists to replace: per-provider response parsing, retry rules, error mapping, cost fields.
- **Provider-side fallback** (for example OpenRouter's own model lists): only covers that one provider, hides which attempt failed, and does not cover Ollama, Groq or Google.
- **LangChain chat models:** a larger dependency for the same job; LangChain stays only where LangGraph needs it (Stage 3).
- **Hosted gateways:** not open source.
- **Run LiteLLM as a proxy server:** a good option for a second language (a Spring service could call it), but an extra service to run. The Python SDK is enough for one API.

## Consequences

- **Footprint:** 32 more packages (including `boto3` and `huggingface-hub`, pulled in by LiteLLM, not used by us) and an API image that grows from 366 MB to 555 MB. Importing LiteLLM takes about 2.7 s at start-up.
- **Release cadence:** LiteLLM ships very often, so Dependabot will propose frequent bumps; each is checked by the gateway tests and the baseline.
- **The fallback order in `models.yaml` is provisional.** Ranking it with the evals needs a real OpenRouter key, which this sub-stage did not have; until then the cloud route is verified only against the scripted provider, and the Ollama route against the live stack.
- **Cool-down state lives in each process,** so several API replicas would not share it.
- **Routing:** one Router per distinct chain, cached.
- Sub-stage 1.3 removes the Ollama route; this module then only handles cloud models.
