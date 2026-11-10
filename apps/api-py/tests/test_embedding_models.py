"""Stage 4.3: choosing the embedding model, noticing a changed one, and the comparison script's
maths (no network, no key, no model download)."""

import sys
from pathlib import Path

import pytest

from app.rag import embeddings, retrieve
from app.rag.embeddings import EmbeddingsUnavailableError

EVALS = Path(__file__).resolve().parents[3] / "evals"


class FakeVector(list):
    def tolist(self):
        return list(self)


class FakeLocalModel:
    """Stands in for FastEmbed's TextEmbedding and records which method was used."""

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(("embed", list(texts)))
        return [FakeVector([1.0, 0.0]) for _ in texts]

    def query_embed(self, texts):
        self.calls.append(("query_embed", list(texts)))
        return [FakeVector([0.0, 1.0]) for _ in texts]


@pytest.fixture
def local_model(monkeypatch):
    model = FakeLocalModel()
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.setattr(embeddings, "_fastembed_model", lambda _name: model)
    monkeypatch.setattr(embeddings, "_fastembed_dimensions", lambda _name: 384)
    return model


def test_google_is_the_default_and_names_its_model_and_size():
    assert embeddings.embedding_model_id() == "google:gemini-embedding-001"
    assert embeddings.embedding_dimensions() == 768


def test_the_open_source_option_names_its_model_and_size(local_model):
    assert embeddings.embedding_model_id() == "fastembed:BAAI/bge-small-en-v1.5"
    assert embeddings.embedding_dimensions() == 384


def test_a_provider_can_be_asked_for_by_name_whatever_is_configured(local_model):
    assert embeddings.embedding_model_id("google") == "google:gemini-embedding-001"
    assert embeddings.embedding_dimensions("google") == 768


@pytest.mark.asyncio
async def test_documents_and_questions_use_the_local_models_two_entry_points(local_model):
    docs = await embeddings.embed_documents(["chunk one", "chunk two"])
    question = await embeddings.embed_query("a question")
    assert docs == [[1.0, 0.0], [1.0, 0.0]] and question == [0.0, 1.0]
    assert [name for name, _ in local_model.calls] == ["embed", "query_embed"]


@pytest.mark.asyncio
async def test_the_local_option_without_its_package_says_how_to_install_it(monkeypatch):
    embeddings._fastembed_model.cache_clear()
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.setitem(sys.modules, "fastembed", None)  # makes `import fastembed` fail
    with pytest.raises(EmbeddingsUnavailableError, match="local-embeddings"):
        await embeddings.embed_query("question")


@pytest.mark.asyncio
async def test_nothing_is_embedded_for_an_empty_list(local_model):
    assert await embeddings.embed_documents([]) == []
    assert local_model.calls == []


# ---------------------------------------------------------- noticing a changed model


@pytest.fixture
def index(monkeypatch):
    retrieve.reset_index_model_check()
    state = {"model": "google:gemini-embedding-001", "reads": 0}

    async def read():
        state["reads"] += 1
        return state["model"]

    monkeypatch.setattr(retrieve, "index_embedding_model", read)
    yield state
    retrieve.reset_index_model_check()


@pytest.mark.asyncio
async def test_a_matching_index_passes_and_is_checked_only_once_per_cache_period(index):
    await retrieve.check_index_model()
    await retrieve.check_index_model()
    assert index["reads"] == 1


@pytest.mark.asyncio
async def test_a_changed_model_stops_the_search_and_says_to_re_ingest(index, monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    with pytest.raises(retrieve.EmbeddingModelMismatchError) as caught:
        await retrieve.check_index_model()
    message = str(caught.value)
    assert (
        "google:gemini-embedding-001" in message and "fastembed:BAAI/bge-small-en-v1.5" in message
    )
    assert "Ingest documents" in message
    assert isinstance(caught.value, EmbeddingsUnavailableError)  # so the API answers 503, not 500


@pytest.mark.asyncio
async def test_an_index_that_records_no_model_is_not_checked(index):
    index["model"] = None
    await retrieve.check_index_model()


@pytest.mark.asyncio
async def test_changing_the_configured_model_is_noticed_even_inside_the_cache_period(
    index, monkeypatch
):
    from app.config import reset_settings

    await retrieve.check_index_model()  # passes and is cached for google
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    reset_settings()  # settings are cached; re-read the environment
    with pytest.raises(retrieve.EmbeddingModelMismatchError):
        await retrieve.check_index_model()


# ------------------------------------------------------ the comparison script's maths


@pytest.fixture
def compare():
    sys.path.insert(0, str(EVALS))
    import compare_embeddings

    return compare_embeddings


def test_documents_are_ranked_by_their_best_chunk_and_counted_once(compare):
    ranked, top = compare.rank_documents(
        [1.0, 0.0],
        [[0.2, 1.0], [1.0, 0.1], [0.9, 0.5]],  # doc B has the best chunk; A's best is its 3rd
        ["A", "B", "A"],
        retrieve.cosine,
    )
    assert ranked == ["B", "A"]
    assert top == pytest.approx(retrieve.cosine([1.0, 0.0], [1.0, 0.1]))


def test_the_summary_reports_recall_mrr_and_the_similarity_gap(compare):
    cases = [
        {"id": "1", "relevant": ["a.md"], "ranked": ["a.md", "b.md"], "top_score": 0.8},
        {"id": "2", "relevant": ["b.md"], "ranked": ["a.md", "b.md"], "top_score": 0.7},
        {"id": "3", "relevant": [], "ranked": ["a.md"], "top_score": 0.5},
    ]
    summary = compare.summarise(cases)
    assert summary["recall_at_1"] == 0.5 and summary["recall_at_3"] == 1.0
    assert summary["mrr"] == pytest.approx(0.75)
    assert summary["similarity_gap"] == pytest.approx(
        0.2
    )  # 0.7 lowest answerable, 0.5 highest unanswerable
