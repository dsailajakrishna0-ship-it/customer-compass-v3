"""Dispatches generation to the configured LLM backend (ported from
apps/api/src/llm/provider.ts).

Both backends are always available side by side; nothing is replaced.
`provider` is an explicit per-request choice (e.g. from a UI selector); when
omitted it falls back to LLM_PROVIDER (defaults to "ollama" — unchanged
Stage 2 behavior). `model` is only used by the "cloud" backend, letting the
caller pick a specific OpenRouter model (see GET /llm/models); when omitted
it falls back to OPENROUTER_MODEL.

Stage 7 adds automatic cross-provider fallback: if the requested provider
raises (timeout, rate-limit, provider outage, etc.), we retry once with the
other provider before giving up, and flag the result as a fallback so the
caller/UI can surface it instead of silently hiding the failure.
"""

import logging
import os
from typing import Literal, get_args

from app.llm.cloud import generate_with_cloud
from app.llm.ollama import generate_with_ollama
from app.llm.types import ChatMessage, GenerationResult

# "ollama" = local generating model, "cloud" = hosted model via OpenRouter
LlmProvider = Literal["ollama", "cloud"]

DEFAULT_LLM_PROVIDER: LlmProvider = os.environ.get("LLM_PROVIDER", "ollama")  # type: ignore[assignment]
if DEFAULT_LLM_PROVIDER not in get_args(LlmProvider):
    DEFAULT_LLM_PROVIDER = "ollama"

logger = logging.getLogger("app.llm.provider")


async def _generate_once(
    resolved: LlmProvider, system_prompt: str, messages: list[ChatMessage], model: str | None
) -> GenerationResult:
    if resolved == "cloud":
        return await generate_with_cloud(system_prompt, messages, model)
    if resolved == "ollama":
        return await generate_with_ollama(system_prompt, messages)
    raise ValueError(f'Unknown LLM provider "{resolved}". Use "ollama" or "cloud".')


async def generate(
    system_prompt: str,
    messages: list[ChatMessage],
    provider: LlmProvider | None = None,
    model: str | None = None,
) -> GenerationResult:
    resolved = provider or DEFAULT_LLM_PROVIDER
    try:
        return await _generate_once(resolved, system_prompt, messages, model)
    except Exception as primary_exc:  # noqa: BLE001 - deliberately broad: any provider failure triggers fallback
        fallback_provider: LlmProvider = "ollama" if resolved == "cloud" else "cloud"
        logger.warning(
            "LLM provider %r failed (%s); falling back to %r", resolved, primary_exc, fallback_provider
        )
        try:
            # model only makes sense for "cloud"; dropped automatically when
            # falling back to "ollama" since generate_with_ollama ignores it.
            fallback_model = model if fallback_provider == "cloud" else None
            result = await _generate_once(fallback_provider, system_prompt, messages, fallback_model)
        except Exception as fallback_exc:  # noqa: BLE001
            logger.warning("Fallback provider %r also failed (%s)", fallback_provider, fallback_exc)
            raise primary_exc
        result.fallback_used = True
        result.fallback_from = resolved
        return result
