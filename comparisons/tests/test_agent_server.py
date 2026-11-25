import pytest
from fastapi.testclient import TestClient
from lab_common.agent import (
    CompanyNotFoundError,
    NotAwaitingApprovalError,
    UnknownRunError,
    create_run_app,
    outcome_for,
)
from lab_common.agent import Recommendation as Rec
from lab_common.chat import UnavailableError

RUN = "0b8f7c2e-6a51-4c0e-9d57-7f1f0b3c1a11"


class FakeAgent:
    approach = "fake"

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def start(self, company, model):
        self.calls.append(("start", company, model))
        if self.error:
            raise self.error
        return outcome_for(RUN, "awaiting_approval", Rec("Call Maya.", "Renewal open."))

    def resume(self, run_id, approve):
        self.calls.append(("resume", run_id, approve))
        if self.error:
            raise self.error
        return outcome_for(
            RUN, "completed" if approve else "declined", Rec("Call Maya.", "Renewal open."), "ok"
        )


def post(agent, path, **kwargs):
    return TestClient(create_run_app(agent)).post(f"/api/v1/agent/{path}", **kwargs)


def test_health_names_the_approach():
    assert TestClient(create_run_app(FakeAgent())).get("/health").json() == {
        "status": "ok",
        "approach": "fake",
    }


def test_start_answers_with_the_four_steps_and_the_recommendation():
    agent = FakeAgent()
    response = post(agent, "start", json={"company": "  Acme ", "model": "x/y"})
    assert response.status_code == 200
    assert response.json() == {
        "runId": RUN,
        "status": "awaiting_approval",
        "steps": [
            {"name": "gather", "status": "done"},
            {"name": "recommend", "status": "done"},
            {"name": "approval", "status": "waiting"},
            {"name": "act", "status": "pending"},
        ],
        "recommendation": {"action": "Call Maya.", "rationale": "Renewal open."},
        "message": "Waiting for approval of the recommended action.",
    }
    assert agent.calls == [("start", "Acme", "x/y")]


def test_resume_passes_the_answer_on_and_a_declined_run_skips_the_act_step():
    agent = FakeAgent()
    body = post(agent, "resume", json={"runId": RUN, "approve": False}).json()
    assert body["status"] == "declined" and [s["status"] for s in body["steps"]] == [
        "done",
        "done",
        "declined",
        "skipped",
    ]
    assert agent.calls == [("resume", RUN, False)]


@pytest.mark.parametrize(
    ("path", "body", "detail"),
    [
        ("start", [], "The body must be a JSON object."),
        ("start", {}, "company is required and must be a non-blank string."),
        ("start", {"company": " "}, "company is required and must be a non-blank string."),
        ("start", {"company": "x" * 201}, "company is limited to 200 characters."),
        (
            "start",
            {"company": "x", "model": 5},
            "model must be a string of at most 100 characters.",
        ),
        (
            "start",
            {"company": "x", "model": "m" * 101},
            "model must be a string of at most 100 characters.",
        ),
        ("resume", {"approve": True}, "runId is required and must be a run id."),
        (
            "resume",
            {"runId": "not a run id!", "approve": True},
            "runId is required and must be a run id.",
        ),
        ("resume", {"runId": RUN}, "approve is required and must be true or false."),
        (
            "resume",
            {"runId": RUN, "approve": "yes"},
            "approve is required and must be true or false.",
        ),
    ],
)
def test_a_bad_request_is_422_with_a_short_detail(path, body, detail):
    response = post(FakeAgent(), path, json=body)
    assert (response.status_code, response.json()) == (422, {"detail": detail})


def test_invalid_json_is_422():
    response = post(
        FakeAgent(), "start", content=b"{nope", headers={"Content-Type": "application/json"}
    )
    assert (response.status_code, response.json()) == (
        422,
        {"detail": "The body is not valid JSON."},
    )


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (CompanyNotFoundError("No company."), 404),
        (UnknownRunError("No run."), 404),
        (NotAwaitingApprovalError("Already answered."), 409),
        (UnavailableError("The CRM could not be reached."), 503),
    ],
)
def test_the_errors_map_to_their_status(error, status):
    response = post(FakeAgent(error), "start", json={"company": "Acme"})
    assert response.status_code == status and response.json()["detail"] == str(error)


def test_anything_else_is_a_fixed_503_message():
    response = post(
        FakeAgent(RuntimeError("http://secret-host/leak")), "start", json={"company": "Acme"}
    )
    assert response.status_code == 503 and "secret" not in response.text
    assert response.json()["detail"] == "The agent could not run."
