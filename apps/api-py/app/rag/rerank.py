"""An optional reranker: a second, more careful model that re-orders the first search results.

Search (dense, or hybrid since 4.1a) is fast but approximate. A *cross-encoder* reranker reads the
question and each candidate chunk together and scores how well they fit, which is slower but more
accurate, so we only use it on a short list. It is a hosted API (ADR 0019): Voyage by default, Cohere
as the alternative, chosen with `RERANK_PROVIDER` (default `off`).

The one rule of this module: **reranking must never break retrieval.** If it is off, has no key, is
slow, is rate-limited or answers nonsense, the caller gets `None` and keeps the original order. Errors
are logged without the key or the provider's reply body.
"""

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger("app.rag.rerank")


@dataclass(frozen=True)
class Provider:
    url: str
    default_model: str
    limit_field: str  # the request field that limits how many results come back
    results_field: str  # the response field that holds the results


PROVIDERS = {
    # https://docs.voyageai.com/reference/reranker-api
    "voyage": Provider("https://api.voyageai.com/v1/rerank", "rerank-2.5-lite", "top_k", "data"),
    # https://docs.cohere.com/reference/rerank
    "cohere": Provider("https://api.cohere.com/v2/rerank", "rerank-v5.0-fast", "top_n", "results"),
}


def reranking_enabled() -> bool:
    return get_settings().rerank_provider != "off"


def _transport() -> httpx.AsyncBaseTransport | None:
    """The network transport; None means the real one. Tests replace this to fake the provider."""
    return None


def _api_key(provider: str) -> str:
    settings = get_settings()
    key = settings.voyage_api_key if provider == "voyage" else settings.cohere_api_key
    return key.get_secret_value()


def _parse(body: object, provider: Provider, count: int, top_n: int) -> list[int] | None:
    """The indexes of the candidates, best first. None if the reply is not a usable ranking."""
    results = body.get(provider.results_field) if isinstance(body, dict) else None
    if not isinstance(results, list):
        return None
    ranked = sorted(
        (r for r in results if isinstance(r, dict)),
        key=lambda r: r.get("relevance_score", 0.0),
        reverse=True,
    )
    order: list[int] = []
    for item in ranked:
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < count and index not in order:
            order.append(index)
    return order[:top_n] or None


async def rerank_order(question: str, texts: list[str], top_n: int) -> list[int] | None:
    """Positions of `texts`, best first, at most `top_n` of them.

    Returns None when reranking is off or did not work; the caller then keeps its own order."""
    settings = get_settings()
    name = settings.rerank_provider
    if name == "off" or len(texts) == 0:
        return None
    provider = PROVIDERS[name]
    api_key = _api_key(name)
    if not api_key:
        logger.warning("rerank_skipped provider=%s reason=no_api_key", name)
        return None

    payload = {
        "model": settings.rerank_model or provider.default_model,
        "query": question,
        "documents": texts,
        provider.limit_field: top_n,
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.rerank_timeout_seconds, transport=_transport()
        ) as client:
            response = await client.post(
                provider.url, json=payload, headers={"Authorization": f"Bearer {api_key}"}
            )
        response.raise_for_status()
        order = _parse(response.json(), provider, len(texts), top_n)
    except (httpx.HTTPError, ValueError) as exc:
        # status code or error type only: the message could echo the request or the key
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning(
            "rerank_failed provider=%s error=%s status=%s", name, type(exc).__name__, status
        )
        return None
    if order is None:
        logger.warning("rerank_failed provider=%s error=unusable_reply", name)
    return order
