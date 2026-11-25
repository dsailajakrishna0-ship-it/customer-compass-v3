"""The withLangChain retrieval approach against a fake embedding model and an in-memory Qdrant
holding vectors of known cosine: no key, no Docker, no network. The second half measures what the
LangChain classes do by themselves (see docs/adr/0039)."""

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from lab_common.chat import UnavailableError
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from rag_retrieval_with_langchain import COLLECTION, LangChainRetrieve

QUERY = [1.0, 0.0]
CHUNKS = {  # name -> (vector, cosine with QUERY)
    "same": [1.0, 0.0],  # 1.0
    "c06": [0.6, 0.8],  # 0.6
    "c03": [0.3, math.sqrt(1 - 0.09)],  # 0.3
    "zero": [0.0, 1.0],  # 0.0
    "opp": [-1.0, 0.0],  # -1.0
}


class FakeEmbeddings(Embeddings):
    def __init__(self, vector=QUERY, fail=False, dimensions=2):
        self.queries: list[str] = []
        self.vector = vector
        self.fail = fail
        self.dimensions = dimensions

    def embed_query(self, text):
        self.queries.append(text)
        if self.fail:
            raise RuntimeError("secret library text http://example.test/key=abc")
        return self.vector

    def embed_documents(self, texts):
        return [self.vector for _ in texts]


@pytest.fixture
def client():
    qdrant = QdrantClient(":memory:")
    qdrant.create_collection(
        COLLECTION, vectors_config=VectorParams(size=2, distance=Distance.COSINE)
    )
    for number, (name, vector) in enumerate(CHUNKS.items(), start=1):
        qdrant.upsert(
            COLLECTION,
            [
                PointStruct(
                    id=number,
                    vector=vector,
                    payload={
                        "page_content": f"text of {name}",
                        "metadata": {
                            "title": name,
                            "source": f"{name}.md",
                            "company": "Acme",
                            "chunk_index": number,
                        },
                    },
                )
            ],
        )
    return qdrant


def retrieve(client, embeddings=None, **kwargs):
    return LangChainRetrieve(
        embeddings=embeddings or FakeEmbeddings(), dimensions=2, qdrant=client, **kwargs
    )


def test_the_chunks_at_or_above_the_floor_are_kept_best_first_with_their_metadata(client):
    result = retrieve(client).search("renewal?", 5, 0.60)
    assert [h.title for h in result.hits] == ["same", "c06"]
    assert result.considered == 5 and result.collection == COLLECTION
    best = result.hits[0]
    assert (best.source, best.company, best.chunk_index, best.text) == (
        "same.md",
        "Acme",
        1,
        "text of same",
    )
    assert best.score == pytest.approx(1.0)


def test_a_chunk_stored_at_exactly_the_floor_is_kept_although_the_score_is_a_widened_float(client):
    hit = retrieve(client).search("q", 5, 0.60).hits[1]
    assert hit.title == "c06" and hit.score == 0.6000000238418579 and hit.score >= 0.60


def test_top_k_limits_how_many_chunks_are_considered(client):
    result = retrieve(client).search("q", 2, 0.0)
    assert result.considered == 2 and [h.title for h in result.hits] == ["same", "c06"]


def test_a_floor_of_zero_keeps_chunks_of_cosine_zero_and_drops_negative_ones(client):
    titles = [h.title for h in retrieve(client).search("q", 5, 0.0).hits]
    assert titles == ["same", "c06", "c03", "zero"]


def test_the_question_is_embedded_once_and_counted(client):
    model = FakeEmbeddings()
    result = retrieve(client, model).search("renewal?", 3, 0.6)
    assert model.queries == ["renewal?"] and result.embedding_requests == 1


def test_a_missing_collection_says_to_run_the_ingestion_first():
    with pytest.raises(UnavailableError, match="Run the withLangChain ingestion first"):
        retrieve(QdrantClient(":memory:")).search("q", 3, 0.6)


def test_a_failing_embedding_is_reported_by_kind_never_by_the_services_text(client):
    with pytest.raises(UnavailableError) as info:
        retrieve(client, FakeEmbeddings(fail=True)).search("q", 3, 0.6)
    assert "secret" not in str(info.value) and "RuntimeError" in str(info.value)


def test_a_vector_of_the_wrong_length_is_refused(client):
    with pytest.raises(UnavailableError, match="wrong length"):
        retrieve(client, FakeEmbeddings(vector=[1.0, 0.0, 0.0])).search("q", 3, 0.6)


def test_no_key_means_no_call(client):
    with pytest.raises(UnavailableError, match="GOOGLE_API_KEY"):
        LangChainRetrieve(qdrant=client).search("q", 3, 0.6)


def test_an_unreachable_qdrant_is_reported_by_kind_not_by_address():
    with pytest.raises(UnavailableError) as info:
        LangChainRetrieve(
            embeddings=FakeEmbeddings(), dimensions=2, qdrant_url="http://127.0.0.1:9"
        ).search("q", 3, 0.6)
    assert "127.0.0.1" not in str(info.value) and str(info.value).startswith("Qdrant failed (")


# What the LangChain classes do on their own (measured).


def store(client, model):
    return QdrantVectorStore(
        client=client,
        collection_name=COLLECTION,
        embedding=model,
        validate_embeddings=False,
        validate_collection_config=False,
    )


def test_measured_the_score_of_similarity_search_with_score_is_the_cosine(client):
    scores = {
        d.page_content: s
        for d, s in store(client, FakeEmbeddings()).similarity_search_with_score("q", k=5)
    }
    assert scores["text of same"] == pytest.approx(1.0)
    assert scores["text of c03"] == pytest.approx(0.3, abs=1e-6)
    assert scores["text of opp"] == pytest.approx(-1.0)


def test_measured_the_relevance_helper_rescales_the_score_to_cosine_plus_one_over_two(client):
    scores = {
        d.page_content: s
        for d, s in store(client, FakeEmbeddings()).similarity_search_with_relevance_scores(
            "q", k=5
        )
    }
    assert scores["text of c06"] == pytest.approx(0.8) and scores["text of opp"] == pytest.approx(
        0.0
    )


def test_measured_the_retriever_threshold_is_on_the_rescaled_scale_so_a_cosine_floor_of_06_keeps_cosine_03(
    client,
):
    retriever = store(client, FakeEmbeddings()).as_retriever(
        search_type="similarity_score_threshold", search_kwargs={"score_threshold": 0.6, "k": 5}
    )
    kept = [d.page_content for d in retriever.invoke("q")]
    assert (
        "text of c03" in kept
    )  # cosine 0.3 is kept by a "0.6" floor: the calibrated number would silently mean something else


def test_measured_score_threshold_on_the_search_call_is_a_cosine_but_hides_how_many_were_found(
    client,
):
    kept = store(client, FakeEmbeddings()).similarity_search_with_score(
        "q", k=5, score_threshold=0.6
    )
    assert [d.page_content for d, _ in kept] == [
        "text of same",
        "text of c06",
    ]  # at or above, but `considered` is gone


def test_measured_every_search_embeds_the_question_once_with_the_store_switches_off(client):
    model = FakeEmbeddings()
    store(client, model).similarity_search_with_score("q", k=3)
    assert model.queries == ["q"]


class FakeGemini(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeGemini.seen.append((self.path, dict(self.headers), body))
        data = json.dumps(
            {"embeddings": [{"values": [1.0, 0.0]} for _ in body["requests"]]}
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def test_measured_the_gemini_class_sends_the_question_as_one_request_with_the_query_task_type_and_the_key_in_a_header(
    client,
):
    FakeGemini.seen = []
    server = HTTPServer(("127.0.0.1", 0), FakeGemini)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = LangChainRetrieve(
            api_key="KEY-123",
            embedding_base_url=f"http://127.0.0.1:{server.server_port}",
            dimensions=2,
            qdrant=client,
        ).search("renewal?", 3, 0.6)
    finally:
        server.shutdown()
    assert [h.title for h in result.hits] == ["same", "c06"] and result.embedding_requests == 1
    assert len(FakeGemini.seen) == 1
    path, headers, body = FakeGemini.seen[0]
    assert (
        path == "/v1beta/models/gemini-embedding-001:batchEmbedContents"
    )  # even one question goes through the batch endpoint
    assert headers["x-goog-api-key"] == "KEY-123" and "KEY-123" not in path
    assert len(body["requests"]) == 1
    assert (
        body["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
        and body["requests"][0]["outputDimensionality"] == 2
    )
