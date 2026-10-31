"""The model gateway: one function, `generate()`, that calls models through LiteLLM.

What it adds over calling a provider directly:

- **An ordered fallback chain.** The requested model is tried first, then the models in
  `fallback_chain` (models.yaml).
- **Failures are told apart.** A 429 (rate limit) moves straight to the next model: retrying a
  rate-limited free model at once is pointless. Timeouts and server errors are retried on the same
  model with growing waits, then fall back.
- **Cool-down.** A model that just failed is skipped for `llm_cooldown_seconds`, so the next
  requests do not hammer it.
- **One result shape.** Callers get a `GenerationResult` whichever model answered, saying
  whether a fallback was used and which model failed first.

Models are hosted free-tier models reached through OpenRouter (V3 is cloud-only, ADR 0010). The
route-building (`build_chain`) is separate from the calling (`generate`) so each can be tested alone.
"""

import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import litellm
import structlog
from litellm import Router
from litellm.integrations.custom_logger import CustomLogger
from litellm.router import RetryPolicy
from litellm.types.router import AllowedFailsPolicy

from app.config import get_model_catalog, get_settings
from app.llm.types import ChatMessage, GenerationResult

# Kept in step with what V2 sent: RAG/CRM answers quote several chunks plus a summary, and a
# smaller limit cut them off mid-sentence.
MAX_RESPONSE_TOKENS = 700
TEMPERATURE = 0.3

log = structlog.stdlib.get_logger("app.llm.gateway")

NO_MODEL_MESSAGE = (
    "No model is configured. Set OPENROUTER_API_KEY (a free key from openrouter.ai) in your .env "
    "and restart the API."
)


class LlmUnavailableError(RuntimeError):
    """Every model in the chain failed. The message is safe to show to the user."""


@dataclass(frozen=True)
class Route:
    """One model the gateway may call."""

    model: str  # the name users see, for example "google/gemma-4-31b-it:free"
    litellm_model: (
        str  # the name LiteLLM needs, for example "openrouter/google/gemma-4-31b-it:free"
    )
    api_key: str | None = field(default=None, repr=False)  # never printed


@dataclass(frozen=True)
class Plan:
    """The models to try in order, plus the first choice (to tell whether a fallback answered)."""

    chain: tuple[Route, ...]
    requested_model: str


def build_chain(model: str | None = None) -> Plan:
    """Turns "which model" into the ordered list of models to try: the requested one (or the
    default), then the `fallback_chain` from models.yaml. Empty when no OpenRouter key is set."""
    settings = get_settings()
    catalogue = get_model_catalog().openrouter
    api_key = settings.openrouter_api_key.get_secret_value()
    first = model or settings.default_openrouter_model
    if not api_key:
        log.warning("openrouter_key_missing")
        return Plan((), first)
    ids = [first, *(m for m in catalogue.fallback_chain if m != first)]
    return Plan(tuple(Route(mid, f"openrouter/{mid}", api_key=api_key) for mid in ids), first)


class _AttemptLogger(CustomLogger):
    """Logs every failed attempt (which model, what kind of error). The request id is attached
    automatically by the logging setup. Never logs prompts, keys or error bodies."""

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        error = kwargs.get("exception")
        log.warning(
            "llm_attempt_failed",
            model=kwargs.get("model"),
            error=type(error).__name__,
            status=getattr(error, "status_code", None),
        )


# LiteLLM's own logs are noisy (a normal fallback is logged at ERROR) and would duplicate ours.
litellm.suppress_debug_info = True
litellm.turn_off_message_logging = True
litellm.callbacks = [_AttemptLogger()]
for _name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy"):
    logging.getLogger(_name).setLevel(logging.CRITICAL)


@lru_cache(maxsize=32)
def _router(
    chain: tuple[Route, ...], timeout: float, retries: int, retry_min: int, cooldown: float
) -> Router:
    """One LiteLLM Router per distinct chain, so cool-down state is remembered between requests."""
    model_list = []
    for index, route in enumerate(chain):
        params: dict[str, Any] = {"model": route.litellm_model, "timeout": timeout}
        if route.api_key:
            params["api_key"] = route.api_key
        model_list.append({"model_name": f"r{index}", "litellm_params": params})
    later = [f"r{i}" for i in range(1, len(chain))]
    return Router(
        model_list=model_list,
        fallbacks=[{"r0": later}] if later else [],
        # 429: no retry on the same model, go to the next. Timeouts and 5xx: retry with backoff.
        retry_policy=RetryPolicy(
            RateLimitErrorRetries=0,
            TimeoutErrorRetries=retries,
            InternalServerErrorRetries=retries,
            AuthenticationErrorRetries=0,
            BadRequestErrorRetries=0,
            ContentPolicyViolationErrorRetries=0,
        ),
        num_retries=retries,
        retry_after=retry_min,
        timeout=timeout,
        # Cool-down: a 429 benches the model at once; a timeout or 5xx only after its retries ran out.
        allowed_fails=retries,
        allowed_fails_policy=AllowedFailsPolicy(
            RateLimitErrorAllowedFails=0,
            AuthenticationErrorAllowedFails=0,
            TimeoutErrorAllowedFails=retries,
            InternalServerErrorAllowedFails=retries,
        ),
        cooldown_time=cooldown,
    )


def _answering_index(response: Any, chain_length: int) -> int:
    """Which route in the chain produced the answer (LiteLLM reports the model group, r0, r1, ...)."""
    hidden = getattr(response, "_hidden_params", None) or {}
    group = str((hidden.get("additional_headers") or {}).get("x-litellm-model-group", "r0"))
    try:
        index = int(group.removeprefix("r"))
    except ValueError:
        return 0
    return index if 0 <= index < chain_length else 0


def _friendly_failure(plan: Plan, error: Exception) -> str:
    tried = ", ".join(r.model for r in plan.chain)
    return (
        f"The model chain is currently unavailable (tried {tried}; last error: "
        f"{type(error).__name__}). Free-tier models rotate and rate-limit often: try again shortly "
        "or pick a different model from the dropdown (the saved list is in apps/api-py/models.yaml)."
    )


async def generate(
    system_prompt: str,
    messages: list[ChatMessage],
    model: str | None = None,
) -> GenerationResult:
    settings = get_settings()
    plan = build_chain(model)
    if not plan.chain:
        raise LlmUnavailableError(NO_MODEL_MESSAGE)
    router = _router(
        plan.chain,
        settings.llm_timeout_seconds,
        settings.llm_max_retries,
        settings.llm_retry_min_seconds,
        settings.llm_cooldown_seconds,
    )
    payload: list[Any] = [{"role": "system", "content": system_prompt}, *messages]
    started = time.perf_counter()
    try:
        response = await router.acompletion(
            model="r0", messages=payload, temperature=TEMPERATURE, max_tokens=MAX_RESPONSE_TOKENS
        )
    except Exception as error:  # noqa: BLE001 - any failure of the whole chain becomes one clear error
        log.warning(
            "llm_chain_failed", tried=[r.model for r in plan.chain], error=type(error).__name__
        )
        raise LlmUnavailableError(_friendly_failure(plan, error)) from error
    latency_ms = round((time.perf_counter() - started) * 1000)

    content = response.choices[0].message.content
    if not content:
        raise LlmUnavailableError(
            "The model returned an empty response. Try again or pick a different model."
        )
    answered = plan.chain[_answering_index(response, len(plan.chain))]
    fallback_used = answered.model != plan.requested_model
    usage = getattr(response, "usage", None)
    hidden = getattr(response, "_hidden_params", None) or {}
    cost = 0.0 if answered.model.endswith(":free") else hidden.get("response_cost")
    if fallback_used:
        log.warning("llm_fallback_used", requested=plan.requested_model, answered=answered.model)
    return GenerationResult(
        content=content,
        model=answered.model,
        tokens_in=getattr(usage, "prompt_tokens", None),
        tokens_out=getattr(usage, "completion_tokens", None),
        latency_ms=latency_ms,
        estimated_cost=cost,
        fallback_used=fallback_used,
        fallback_from_model=plan.requested_model if fallback_used else None,
    )
