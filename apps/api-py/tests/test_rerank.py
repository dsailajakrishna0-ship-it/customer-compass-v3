"""Stage 4.1b: the optional reranker, with a fake provider (no key, no network)."""

import json
import logging

import httpx
import pytest

from app.rag import rerank

SECRET = "sk-test-secret-123"


@pytest.fixture
def log_lines():
    """The reranker's own log lines, captured on its logger directly. (pytest's `caplog` depends on
    the root logger, which the app's logging set-up and other tests reconfigure.)"""
    lines: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    logger = logging.getLogger("app.rag.rerank")
    handler, old = Collect(), (logger.level, logger.disabled)
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    logger.disabled = False
    yield lines
    logger.removeHandler(handler)
    logger.setLevel(old[0])
    logger.disabled = old[1]


@pytest.fixture
def provider(monkeypatch):
    """Selects a provider, gives it a key, and fakes the HTTP server. `reply` is what the server
    answers: a status and a JSON body. The requests the code made are recorded in `seen`."""

    def install(name="voyage", status=200, body=None, error=None, key=SECRET):
        monkeypatch.setenv("RERANK_PROVIDER", name)
        monkeypatch.setenv("VOYAGE_API_KEY" if name == "voyage" else "COHERE_API_KEY", key)
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if error:
                raise error
            return httpx.Response(status, json=body)

        monkeypatch.setattr(rerank, "_transport", lambda: httpx.MockTransport(handler))
        return seen

    return install


TEXTS = ["first", "second", "third"]
VOYAGE_REPLY = {
    "data": [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.4}]
}


@pytest.mark.asyncio
async def test_off_by_default_makes_no_call(monkeypatch):
    def no_network():
        raise AssertionError("a disabled reranker must not touch the network")

    monkeypatch.setattr(rerank, "_transport", no_network)
    assert rerank.reranking_enabled() is False
    assert await rerank.rerank_order("q", TEXTS, 2) is None


@pytest.mark.asyncio
async def test_voyage_request_and_ranking(provider):
    seen = provider("voyage", body=VOYAGE_REPLY)
    assert await rerank.rerank_order("what about pricing?", TEXTS, 2) == [2, 0]
    [request] = seen
    assert str(request.url) == "https://api.voyageai.com/v1/rerank"
    assert request.headers["authorization"] == f"Bearer {SECRET}"
    assert json.loads(request.content) == {
        "model": "rerank-2.5-lite", "query": "what about pricing?", "documents": TEXTS, "top_k": 2,
    }  # fmt: skip


@pytest.mark.asyncio
async def test_cohere_request_and_ranking(provider):
    seen = provider("cohere", body={"results": [{"index": 1, "relevance_score": 0.7}]})
    assert await rerank.rerank_order("q", TEXTS, 3) == [1]
    [request] = seen
    assert str(request.url) == "https://api.cohere.com/v2/rerank"
    assert json.loads(request.content)["top_n"] == 3
    assert json.loads(request.content)["model"] == "rerank-v5.0-fast"


@pytest.mark.asyncio
async def test_the_provider_reply_is_sorted_by_score_not_trusted_for_order(provider):
    provider("voyage", body={"data": [
        {"index": 0, "relevance_score": 0.1}, {"index": 1, "relevance_score": 0.8},
    ]})  # fmt: skip
    assert await rerank.rerank_order("q", TEXTS, 2) == [1, 0]


@pytest.mark.asyncio
async def test_a_configured_model_overrides_the_default(provider, monkeypatch):
    seen = provider("voyage", body=VOYAGE_REPLY)
    monkeypatch.setenv("RERANK_MODEL", "rerank-2.5")
    from app.config import reset_settings

    reset_settings()
    await rerank.rerank_order("q", TEXTS, 2)
    assert json.loads(seen[0].content)["model"] == "rerank-2.5"


@pytest.mark.asyncio
async def test_no_key_means_no_call_and_a_warning(provider, log_lines):
    seen = provider("voyage", body=VOYAGE_REPLY, key="")
    assert await rerank.rerank_order("q", TEXTS, 2) is None
    assert seen == [] and any("no_api_key" in line for line in log_lines)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": 429, "body": {"detail": "rate limited"}},
        {"status": 500, "body": {}},
        {"error": httpx.ReadTimeout("slow")},
        {"error": httpx.ConnectError("down")},
        {"body": {"unexpected": True}},
        {"body": {"data": []}},
        {"body": {"data": [{"index": 99, "relevance_score": 1.0}]}},
        {"body": "not json shaped"},
    ],
)
async def test_every_failure_returns_none_so_the_search_order_stays(provider, kwargs):
    provider("voyage", **kwargs)
    assert await rerank.rerank_order("q", TEXTS, 2) is None


@pytest.mark.asyncio
async def test_a_failure_is_logged_without_the_key_or_the_reply(provider, log_lines):
    provider("voyage", status=401, body={"detail": f"bad key {SECRET}"})
    await rerank.rerank_order("q", TEXTS, 2)
    text = "\n".join(log_lines)
    assert "rerank_failed" in text and "status=401" in text
    assert SECRET not in text and "bad key" not in text


@pytest.mark.asyncio
async def test_duplicate_and_out_of_range_indexes_are_ignored(provider):
    provider("voyage", body={"data": [
        {"index": 1, "relevance_score": 0.9}, {"index": 1, "relevance_score": 0.8},
        {"index": 7, "relevance_score": 0.7}, {"index": 0, "relevance_score": 0.1},
    ]})  # fmt: skip
    assert await rerank.rerank_order("q", TEXTS, 5) == [1, 0]
