"""Stage 4.1a: hybrid retrieval, with a fake Qdrant client (no database, no key)."""

from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.rag import retrieve


def test_rrf_prefers_what_both_rankings_like():
    assert retrieve.rrf_fuse([["a", "b", "c"], ["b", "d", "a"]])[:2] == ["b", "a"]


def test_rrf_uses_positions_not_scores_and_keeps_items_found_by_only_one_search():
    merged = retrieve.rrf_fuse([["a", "b"], ["c"]])
    assert set(merged) == {"a", "b", "c"}
    assert merged[:2] == ["a", "c"]  # both are first in their own ranking: a tie, a is listed first


def test_rrf_with_one_empty_ranking_is_the_other_ranking():
    assert retrieve.rrf_fuse([["a", "b", "c"], []]) == ["a", "b", "c"]
    assert retrieve.rrf_fuse([]) == []


def test_cosine():
    assert retrieve.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert retrieve.cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert retrieve.cosine([0, 0], [1, 1]) == 0.0


def _point(point_id, score, title, vector=None):
    payload = {
        "document_id": 1, "chunk_index": 0, "content": f"text of {title}",
        "document_title": title, "source_path": f"{title}.md", "doc_type": "note",
        "company_name": None,
    }  # fmt: skip
    return SimpleNamespace(id=point_id, score=score, payload=payload, vector=vector)


class FakeQdrant:
    """Answers the two searches by which named vector is asked for, and records the calls."""

    def __init__(self, dense, keyword):
        self.dense, self.keyword, self.calls = dense, keyword, []

    async def count(self, **_kwargs):
        return SimpleNamespace(count=10)

    async def query_points(self, **kwargs):
        self.calls.append(kwargs)
        points = self.dense if kwargs["using"] == "dense" else self.keyword
        return SimpleNamespace(points=points)


@pytest.fixture
def fake(monkeypatch):
    async def embed(_text):
        return [1.0, 0.0]

    monkeypatch.setattr(retrieve, "embed_text", embed)
    retrieve.reset_count_cache()

    def install(dense, keyword, mode):
        client = FakeQdrant(dense, keyword)
        monkeypatch.setattr(retrieve, "get_client", lambda: client)
        monkeypatch.setenv("RETRIEVAL_MODE", mode)
        return client

    yield install
    retrieve.reset_count_cache()


@pytest.mark.asyncio
async def test_dense_mode_asks_only_the_dense_vector_and_keeps_the_old_behaviour(fake):
    client = fake([_point("a", 0.8, "A"), _point("b", 0.3, "B")], [], "dense")
    chunks = await retrieve.retrieve_relevant_chunks("question")
    assert [c.document_title for c in chunks] == ["A"]  # B is under MIN_SIMILARITY
    assert [call["using"] for call in client.calls] == ["dense"]


@pytest.mark.asyncio
async def test_hybrid_mode_asks_both_vectors_and_merges_the_rankings(fake):
    dense = [_point("a", 0.9, "A"), _point("b", 0.8, "B"), _point("c", 0.7, "C")]
    keyword = [_point("c", 5.0, "C"), _point("b", 3.0, "B")]
    client = fake(dense, keyword, "hybrid")
    chunks = await retrieve.retrieve_relevant_chunks("question", top_k=3)
    assert sorted(call["using"] for call in client.calls) == ["bm25", "dense"]
    # b and c are in both rankings, a only in one; c is first in the keyword ranking, so c edges b
    assert [c.document_title for c in chunks] == ["C", "B", "A"]
    assert {c.document_title: c.similarity for c in chunks} == {"A": 0.9, "B": 0.8, "C": 0.7}


@pytest.mark.asyncio
async def test_a_keyword_only_hit_gets_its_meaning_similarity_from_its_dense_vector(fake):
    # "k" matches the exact words but is not in the dense top results; its stored dense vector is
    # close to the question's (1, 0), so it passes the similarity floor
    keyword = [_point("k", 9.0, "K", vector={"dense": [0.9, 0.1]})]
    fake([_point("a", 0.8, "A")], keyword, "hybrid")
    chunks = await retrieve.retrieve_relevant_chunks("exact words")
    assert {c.document_title for c in chunks} == {"A", "K"}
    k = next(c for c in chunks if c.document_title == "K")
    assert k.similarity == pytest.approx(0.9 / (0.81 + 0.01) ** 0.5, rel=1e-6)


@pytest.mark.asyncio
async def test_an_unrelated_keyword_hit_is_still_dropped_by_the_similarity_floor(fake):
    # it shares a word with the question, but its meaning is far from it: not worth citing
    keyword = [_point("k", 2.0, "K", vector={"dense": [0.0, 1.0]})]
    fake([], keyword, "hybrid")
    assert await retrieve.retrieve_relevant_chunks("a common word") == []


@pytest.mark.asyncio
async def test_a_question_with_no_words_skips_the_keyword_search(fake):
    client = fake([_point("a", 0.8, "A")], [], "hybrid")
    chunks = await retrieve.retrieve_relevant_chunks("?!")
    assert [c.document_title for c in chunks] == ["A"]
    assert [call["using"] for call in client.calls] == ["dense"]


def test_the_default_mode_is_dense_so_nothing_changes_until_it_is_chosen():
    assert get_settings().retrieval_mode == "dense"
