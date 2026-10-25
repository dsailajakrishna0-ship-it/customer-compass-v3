"""Calls the OpenRouter cloud model (ported from apps/api/src/llm/cloud.ts,
Stage 4 swappable alternative to Ollama).

OpenRouter exposes an OpenAI-compatible /chat/completions endpoint and
offers several free-tier models (suffixed ":free"). See
https://openrouter.ai/models?max_price=0 for the current free-model list, or
GET /llm/models on this API (backs the web UI's model dropdown).
"""

import os
import time

import httpx

from app.llm.types import ChatMessage, GenerationResult

# Enables cloud LLMs: OpenRouter is an OpenAI-compatible gateway to hosted models
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# RAG/CRM answers often quote multiple cited chunks plus a summary; 350 was
# cutting those off mid-sentence (observed during Stage 6 manual testing).
MAX_RESPONSE_TOKENS = 700
DEFAULT_OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "liquid/lfm-2.5-2.6b:free")

# Stage 7 cost tracking: every model the web UI's dropdown currently offers is
# a ":free" OpenRouter model (GET /llm/models filters to free + a disabled
# paid group), so the real-world cost today is always $0. This map exists so
# a real per-token price can be dropped in per-model later (e.g. once paid
# models are enabled) without touching the call sites that read
# GenerationResult.estimated_cost.
OPENROUTER_PRICE_PER_1K_TOKENS: dict[str, float] = {}


def _estimate_cost(model: str, tokens_in: int | None, tokens_out: int | None) -> float | None:
    if model.endswith(":free"):
        return 0.0
    price = OPENROUTER_PRICE_PER_1K_TOKENS.get(model)
    if price is None or tokens_in is None or tokens_out is None:
        return None
    return round((tokens_in + tokens_out) / 1000 * price, 6)


async def generate_with_cloud(
    system_prompt: str, messages: list[ChatMessage], model: str | None = None
) -> GenerationResult:
    """`model` is an optional per-request override (from the web UI's "OpenRouter
    model" dropdown); when omitted, falls back to OPENROUTER_MODEL / the
    hardcoded default above."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set. Add it to apps/api-py/.env to use LLM_PROVIDER=cloud.")

    resolved_model = model or DEFAULT_OPENROUTER_MODEL

    started_at = time.perf_counter()
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": resolved_model,
                "temperature": 0.3,
                "max_tokens": MAX_RESPONSE_TOKENS,
                "messages": [{"role": "system", "content": system_prompt}, *messages],
            },
        )
    latency_ms = round((time.perf_counter() - started_at) * 1000)
    payload = response.json()

    # OpenRouter can return HTTP 200 with an embedded `error` object when the
    # upstream free-tier provider is overloaded/rate-limited, so we must check
    # for that in addition to a non-2xx status.
    error = payload.get("error")
    if response.status_code != 200 or error:
        detail = (error or {}).get("message") or response.text
        raise RuntimeError(
            f"The cloud model ({resolved_model}) is currently unavailable: {detail or 'unknown error'}. "
            "Free-tier models rotate/rate-limit often - try again shortly or pick a different model "
            "from the dropdown (see apps/api-py/.env.example for how to refresh the free-model list)."
        )

    content = (payload.get("choices") or [{}])[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError("The cloud model returned an empty response. Try again or pick a different model.")

    usage = payload.get("usage") or {}
    tokens_in = usage.get("prompt_tokens")
    tokens_out = usage.get("completion_tokens")
    return GenerationResult(
        content=content,
        provider="cloud",
        model=resolved_model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        estimated_cost=_estimate_cost(resolved_model, tokens_in, tokens_out),
    )
