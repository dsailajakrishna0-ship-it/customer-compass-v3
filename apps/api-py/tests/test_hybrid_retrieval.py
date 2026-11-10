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

    async def no_check():
        return None

    monkeypatch.setattr(retrieve, "embed_text", embed)
    monkeypatch.setattr(retrieve, "check_index_model", no_check)
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


# ---------------------------------------------------------------- with a reranker (Stage 4.1b)


@pytest.fixture
def reranker(monkeypatch):
    """Turns reranking on and replaces the provider call. `answer` is the order it returns
    (positions in the shortlist) or None for a failure; `calls` records what it was sent."""
    monkeypatch.setenv("RERANK_PROVIDER", "voyage")
    calls = []

    def install(answer):
        async def fake(question, texts, top_n):
            calls.append((question, texts, top_n))
            return answer

        monkeypatch.setattr(retrieve, "rerank_order", fake)
        return calls

    return install


@pytest.mark.asyncio
async def test_the_reranker_decides_the_final_order_from_a_longer_shortlist(fake, reranker):
    dense = [_point(i, 0.9 - i / 100, f"T{i}") for i in range(6)]
    fake(dense, [], "dense")
    calls = reranker([5, 1])  # it prefers the 6th and the 2nd chunk
    chunks = await retrieve.retrieve_relevant_chunks("question", top_k=2)
    assert [c.document_title for c in chunks] == ["T5", "T1"]
    [(question, texts, top_n)] = calls
    assert question == "question" and top_n == 2
    assert len(texts) == 6 and texts[0] == "T0: text of T0"  # the whole shortlist, with titles


@pytest.mark.asyncio
async def test_without_a_reranker_only_top_k_is_fetched_as_before(fake):
    client = fake([_point(i, 0.9, f"T{i}") for i in range(6)], [], "dense")
    await retrieve.retrieve_relevant_chunks("question", top_k=2)
    assert client.calls[0]["limit"] == 2


@pytest.mark.asyncio
async def test_a_failed_reranker_keeps_the_search_order(fake, reranker):
    dense = [_point(i, 0.9 - i / 100, f"T{i}") for i in range(6)]
    fake(dense, [], "dense")
    reranker(None)
    chunks = await retrieve.retrieve_relevant_chunks("question", top_k=3)
    assert [c.document_title for c in chunks] == ["T0", "T1", "T2"]


@pytest.mark.asyncio
async def test_the_similarity_floor_still_applies_before_the_reranker(fake, reranker):
    fake([_point("a", 0.8, "A"), _point("b", 0.2, "B")], [], "dense")
    calls = reranker([0])
    chunks = await retrieve.retrieve_relevant_chunks("question")
    assert [c.document_title for c in chunks] == ["A"]
    assert calls == []  # a single candidate needs no reranking


@pytest.mark.asyncio
async def test_hybrid_mode_reranks_the_merged_shortlist(fake, reranker):
    dense = [_point("a", 0.9, "A"), _point("b", 0.8, "B")]
    keyword = [_point("b", 5.0, "B"), _point("c", 4.0, "C", vector={"dense": [0.9, 0.1]})]
    fake(dense, keyword, "hybrid")
    calls = reranker([2, 0])
    chunks = await retrieve.retrieve_relevant_chunks("question", top_k=2)
    assert len(calls[0][1]) == 3  # a, b and c all reached the reranker
    assert len(chunks) == 2
