"""Lists OpenRouter's current free-tier models plus a couple of disabled paid
examples (ported from apps/api/src/routes/llm.ts), so the web UI can offer a
live "OpenRouter model" dropdown instead of only the single
server-configured OPENROUTER_MODEL default.

Cached briefly since OpenRouter's public /models catalog is large and
doesn't change second-to-second.
"""

import time

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/llm", tags=["llm"])

# A couple of well-known paid models shown for reference only, so a learner
# can see what "the same dropdown, but paid" looks like. These are never
# selectable — the UI renders them disabled/greyed out.
PAID_EXAMPLE_MODEL_IDS = {"openai/gpt-4o-mini", "anthropic/claude-sonnet-4"}

CACHE_TTL_SECONDS = 5 * 60
_cache: dict | None = None


# Feeds the UI model picker with OpenRouter's catalogue of hosted models (cached 5 min)
@router.get("/models")
async def list_models():
    global _cache
    if _cache and time.monotonic() - _cache["fetched_at"] < CACHE_TTL_SECONDS:
        return {"free": _cache["free"], "paid": _cache["paid"]}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            upstream = await client.get("https://openrouter.ai/api/v1/models")
        if upstream.status_code != 200:
            raise RuntimeError(f"OpenRouter /models returned {upstream.status_code}")
        models = upstream.json().get("data") or []

        free = sorted(
            ({"id": m["id"], "name": m["name"]} for m in models if m["id"].endswith(":free")),
            key=lambda m: m["name"],
        )
        paid = [{"id": m["id"], "name": m["name"]} for m in models if m["id"] in PAID_EXAMPLE_MODEL_IDS]

        _cache = {"fetched_at": time.monotonic(), "free": free, "paid": paid}
        return {"free": free, "paid": paid}
    except Exception as exc:  # noqa: BLE001 - mirrors the Express route's catch-all 503
        raise HTTPException(status_code=503, detail="Could not reach OpenRouter to list available models.") from exc
