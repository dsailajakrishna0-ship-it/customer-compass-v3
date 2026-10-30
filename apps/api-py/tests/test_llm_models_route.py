"""The model dropdown route: live list when OpenRouter answers, models.yaml when it does not."""

import httpx
import pytest
from fastapi import FastAPI

from app.config import get_model_catalog
from app.routes import llm as llm_route

REAL_CLIENT = httpx.AsyncClient  # the route's client is patched; the test's own must stay real


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "data": [
                {"id": "b/free-two:free", "name": "B two"},
                {"id": "a/free-one:free", "name": "A one"},
                {"id": "openai/gpt-4o-mini", "name": "GPT-4o mini"},
                {"id": "other/paid", "name": "Not listed"},
            ]
        }


def fake_client(calls: list, fail: bool = False):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            calls.append(url)
            if fail:
                raise httpx.ConnectError("no network")
            return FakeResponse()

    return FakeClient


@pytest.fixture(autouse=True)
def _clean_cache():
    llm_route._cache = None
    yield
    llm_route._cache = None


async def call() -> dict:
    app = FastAPI()
    app.include_router(llm_route.router, prefix="/api/v1")
    async with REAL_CLIENT(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/llm/models")
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_live_list_is_sorted_filtered_and_cached(monkeypatch):
    calls: list = []
    monkeypatch.setattr(llm_route.httpx, "AsyncClient", fake_client(calls))
    body = await call()
    assert body["source"] == "live"
    assert [m["id"] for m in body["free"]] == ["a/free-one:free", "b/free-two:free"]
    assert [m["id"] for m in body["paid"]] == ["openai/gpt-4o-mini"]
    await call()
    assert len(calls) == 1, "the second request is served from the cache"


@pytest.mark.asyncio
async def test_falls_back_to_models_yaml_when_openrouter_is_unreachable(monkeypatch):
    monkeypatch.setattr(llm_route.httpx, "AsyncClient", fake_client([], fail=True))
    body = await call()
    assert body["source"] == "fallback"
    assert [m["id"] for m in body["free"]] == [
        m.id for m in get_model_catalog().openrouter.last_known_good
    ]
    assert body["paid"] == []
