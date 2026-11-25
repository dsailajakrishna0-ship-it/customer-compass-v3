import pytest
from fastapi.testclient import TestClient
from lab_common.chat import UnavailableError
from lab_common.ingest import IngestResult, create_ingest_app


class FakeIngest:
    approach = "fake"

    def __init__(self, error=None):
        self.error = error
        self.limit = "not called"

    def run(self, limit):
        self.limit = limit
        if self.error:
            raise self.error
        return IngestResult("compare_fake", 3, 7, 1, "gemini-embedding-001", 768, 42)


def post(ingest, **kwargs):
    return TestClient(create_ingest_app(ingest)).post("/api/v1/ingest", **kwargs)


def test_health_names_the_approach():
    assert TestClient(create_ingest_app(FakeIngest())).get("/health").json() == {
        "status": "ok",
        "approach": "fake",
    }


def test_a_run_answers_with_the_counts_and_no_limit_by_default():
    ingest = FakeIngest()
    response = post(ingest)
    assert response.status_code == 200
    assert response.json() == {
        "approach": "fake",
        "status": "completed",
        "collection": "compare_fake",
        "documents": 3,
        "chunks": 7,
        "embeddingRequests": 1,
        "embeddingModel": "gemini-embedding-001",
        "dimensions": 768,
        "latencyMs": 42,
    }
    assert ingest.limit is None


def test_a_limit_is_passed_on():
    ingest = FakeIngest()
    post(ingest, json={"limit": 3})
    assert ingest.limit == 3


@pytest.mark.parametrize(
    "body", [{"limit": 0}, {"limit": 1001}, {"limit": "3"}, {"limit": True}, {"limit": 2.5}]
)
def test_a_bad_limit_is_422(body):
    response = post(FakeIngest(), json=body)
    assert (response.status_code, response.json()) == (
        422,
        {"detail": "limit must be an integer from 1 to 1000."},
    )


def test_a_body_that_is_not_an_object_or_not_json_is_422():
    assert post(FakeIngest(), json=[1]).json() == {"detail": "The body must be a JSON object."}
    bad = post(FakeIngest(), content=b"{nope", headers={"Content-Type": "application/json"})
    assert (bad.status_code, bad.json()) == (422, {"detail": "The body is not valid JSON."})


def test_unavailable_is_503_with_its_message_and_anything_else_is_a_fixed_message():
    one = post(
        FakeIngest(UnavailableError("GOOGLE_API_KEY is not set. Put it in the environment."))
    )
    assert (one.status_code, one.json()["detail"]) == (
        503,
        "GOOGLE_API_KEY is not set. Put it in the environment.",
    )
    two = post(FakeIngest(RuntimeError("http://secret-host/leak")))
    assert (
        two.status_code == 503
        and "secret" not in two.text
        and two.json()["detail"] == "Could not ingest."
    )
