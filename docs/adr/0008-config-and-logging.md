# 0008 — Settings, model catalogue and structured logging

- **Status:** Accepted
- **Date:** 2026-10-30
- **Roadmap sub-stage:** 1.1

## Context

V2 read configuration with 22 `os.environ` reads spread over 12 files, each with its own default and its own (sometimes missing) validation. An invalid value was sometimes silently replaced (`LLM_PROVIDER=openrouter` became `ollama`), secrets were plain strings, the free-model list lived only in OpenRouter's live catalogue (the dropdown returned 503 when it was unreachable), and logs were unstructured text with no way to follow one request.

## Decision

- **`app/config.py` is the only module that reads the environment.** A typed `Settings` class (`pydantic-settings` 2.16) holds every setting; `get_settings()` builds it once, `reset_settings()` re-reads it (used by tests). A test fails if any other file under `app/` touches `os.environ`.
- **Fail fast.** A wrong value (for example a provider name that does not exist) stops start-up with a message naming the setting. This replaces the old silent fallback to a default.
- **Empty means unset** (`env_ignore_empty`), because Compose passes `VAR: ${VAR:-}` as an empty string.
- **Secrets are `SecretStr`.** They print as `**********`, so a log line or error cannot leak them.
- **`apps/api-py/models.yaml`** holds the default OpenRouter model and a last-known-good list of free models, validated at load (the default must be listed; test: free tier only). `OPENROUTER_MODEL` still overrides the default. `GET /api/v1/llm/models` serves the saved list, with `"source": "fallback"`, when OpenRouter cannot be reached, instead of returning 503. Stage 1.2 builds the ordered fallback chain on this file.
- **Logging with `structlog` 26.1.** One JSON object per line (`LOG_FORMAT=console` for readable output), with the existing standard-library loggers routed through the same pipeline so every line carries the request id without being rewritten.
- **Request ids.** A small ASGI middleware accepts the caller's `X-Request-ID` if it is a plain token (letters, digits, `.`, `_`, `-`, up to 64 characters), otherwise generates one; binds it to the logging context; returns it in the response header; and logs one summary line per request (health checks at debug level). `--no-access-log` replaces uvicorn's access line with it. The id becomes the trace id when Langfuse arrives in Stage 5.1.
- **httpx and httpcore are kept at WARNING.** The embeddings call passes the Google key in the URL (`?key=...`), and httpx logs request URLs at INFO. A regression test proves the key stays out of the logs.

## Alternatives considered

- **Dynaconf or plain `python-dotenv`:** less typing and validation than pydantic-settings, which is already a dependency of the tools we adopt next.
- **Loading `.env` inside the app:** Compose and the eval runner already provide the environment; reading a file here would let a developer's local file change test results.
- **Keeping the model list only in code or only live from OpenRouter:** a file is easy to review and gives a fallback when the live list fails.
- **`loguru`:** pleasant API, but the stack standard for structured, context-bound logs (and the OpenTelemetry path) is stronger with structlog.
- **Request-id libraries such as `asgi-correlation-id`:** about 60 lines of middleware are clearer for learning and have no extra dependency.

## Consequences

- Behaviour changes, on purpose: a wrong `LLM_PROVIDER`, `GUARD_MODE` or `GUARD_PROVIDER` now stops start-up instead of silently using a default; the model dropdown no longer returns 503; logs are JSON by default.
- Settings are read when first used and then cached; code that needs a changed environment in a test calls `reset_settings()` (an autouse fixture does it for every test).
- The free-model list in `models.yaml` ages. Each id was checked against OpenRouter's catalogue on 2026-10-30, and `test_config.py` checks the file's structure, not whether the models still exist.
- The Alembic `env.py` now reads the database URL from the same settings.
