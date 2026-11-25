import pytest
from fastapi.testclient import TestClient
from lab_common.chat import UnavailableError
from lab_common.retrieve import Hit, RetrieveResult, create_retrieve_app


class FakeRetrieve:
    approach = "fake"

    def __init__(self, error=None):
        self.error = error
        self.args = None

    def search(self, query, top_k, min_similarity):
        self.args = (query, top_k, min_similarity)
        if self.error:
            raise self.error
        hit = Hit(0.72, "Renewal call", "acme-call-renewal.md", "Acme Fabrication", 1, "text")
        return RetrieveResult(
            "compare_fake", min_similarity, 4, [hit], 1, "gemini-embedding-001", 9
        )


def post(retrieve, **kwargs):
    return TestClient(create_retrieve_app(retrieve)).post("/api/v1/retrieve", **kwargs)


def test_health_names_the_approach():
    assert TestClient(create_retrieve_app(FakeRetrieve())).get("/health").json() == {
        "status": "ok",
        "approach": "fake",
    }


def test_a_search_answers_with_the_hits_and_the_defaults():
    retrieve = FakeRetrieve()
    response = post(retrieve, json={"query": "  renewal?  "})
    assert response.status_code == 200
    assert response.json() == {
        "approach": "fake",
        "collection": "compare_fake",
        "minSimilarity": 0.6,
        "considered": 4,
        "kept": 1,
        "hits": [
            {
                "score": 0.72,
                "title": "Renewal call",
                "source": "acme-call-renewal.md",
                "company": "Acme Fabrication",
                "chunkIndex": 1,
                "text": "text",
            }
        ],
        "embeddingRequests": 1,
        "embeddingModel": "gemini-embedding-001",
        "latencyMs": 9,
    }
    assert retrieve.args == ("renewal?", 4, 0.6)


def test_top_k_and_the_floor_are_passed_on():
    retrieve = FakeRetrieve()
    post(retrieve, json={"query": "x", "topK": 7, "minSimilarity": 0.5})
    assert retrieve.args == ("x", 7, 0.5)


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ([], "The body must be a JSON object."),
        ({}, "query is required and must be a non-blank string."),
        ({"query": "  "}, "query is required and must be a non-blank string."),
        ({"query": "x" * 1001}, "query is limited to 1000 characters."),
        ({"query": "x", "topK": 0}, "topK must be an integer from 1 to 20."),
        ({"query": "x", "topK": 21}, "topK must be an integer from 1 to 20."),
        ({"query": "x", "topK": "3"}, "topK must be an integer from 1 to 20."),
        ({"query": "x", "minSimilarity": 1.5}, "minSimilarity must be a number from 0 to 1."),
        ({"query": "x", "minSimilarity": True}, "minSimilarity must be a number from 0 to 1."),
    ],
)
def test_a_bad_request_is_422_with_a_short_detail(body, detail):
    response = post(FakeRetrieve(), json=body)
    assert (response.status_code, response.json()) == (422, {"detail": detail})


def test_an_empty_body_or_invalid_json_is_422():
    assert post(FakeRetrieve()).json() == {"detail": "The body must be a JSON object with a query."}
    bad = post(FakeRetrieve(), content=b"{nope", headers={"Content-Type": "application/json"})
    assert (bad.status_code, bad.json()) == (422, {"detail": "The body is not valid JSON."})


def test_unavailable_is_503_with_its_message_and_anything_else_is_a_fixed_message():
    one = post(FakeRetrieve(UnavailableError("The collection is missing.")), json={"query": "x"})
    assert (one.status_code, one.json()["detail"]) == (503, "The collection is missing.")
    two = post(FakeRetrieve(RuntimeError("http://secret-host/leak")), json={"query": "x"})
    assert (
        two.status_code == 503
        and "secret" not in two.text
        and two.json()["detail"] == "Could not search."
    )
