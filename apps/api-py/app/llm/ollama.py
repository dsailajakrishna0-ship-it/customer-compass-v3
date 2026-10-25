"""Calls the local Ollama chat model (ported from apps/api/src/llm/ollama.ts,
Stage 2 behavior, unchanged)."""

import os
import time

import httpx

from app.llm.types import ChatMessage, GenerationResult

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11435")
# Generating (chat) model: Ollama qwen2.5:3b runs locally to write the answer
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
# Kept in sync with cloud.py's MAX_RESPONSE_TOKENS — same truncation issue
# affects both providers for multi-citation RAG/CRM answers.
MAX_RESPONSE_TOKENS = 700


async def generate_with_ollama(system_prompt: str, messages: list[ChatMessage]) -> GenerationResult:
    started_at = time.perf_counter()
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": [{"role": "system", "content": system_prompt}, *messages],
                "options": {"temperature": 0.3, "num_predict": MAX_RESPONSE_TOKENS},
            },
        )
    latency_ms = round((time.perf_counter() - started_at) * 1000)
    if response.status_code != 200:
        raise RuntimeError("The local model is not ready. Start Ollama and pull the configured model.")
    payload = response.json()
    content = payload.get("message", {}).get("content") or "I could not generate a response."
    # Ollama's /api/chat reports token counts as prompt_eval_count (input) and
    # eval_count (output); local inference has no per-token billing, so cost
    # is always $0.
    return GenerationResult(
        content=content,
        provider="ollama",
        model=OLLAMA_MODEL,
        tokens_in=payload.get("prompt_eval_count"),
        tokens_out=payload.get("eval_count"),
        latency_ms=latency_ms,
        estimated_cost=0.0,
    )
