import pytest

from app.config import get_settings
from app.rag import retrieve


def test_small_collection_uses_exact_search():
    strategy, params = retrieve.choose_search_strategy(get_settings().vector_index_min_points - 1)
    assert strategy == "exact"
    assert params.exact is True


def test_threshold_and_above_use_hnsw():
    strategy, params = retrieve.choose_search_strategy(get_settings().vector_index_min_points)
    assert strategy == "hnsw"
    assert params.hnsw_ef == get_settings().vector_hnsw_ef
    assert not params.exact


@pytest.mark.asyncio
async def test_point_count_is_cached(monkeypatch):
    calls = 0

    class FakeClient:
        async def count(self, **_kwargs):
            nonlocal calls
            calls += 1
            return type("R", (), {"count": 42})()

    monkeypatch.setattr(retrieve, "get_client", lambda: FakeClient())
    retrieve.reset_count_cache()
    assert await retrieve.get_point_count() == 42
    assert await retrieve.get_point_count() == 42
    assert calls == 1
    retrieve.reset_count_cache()
