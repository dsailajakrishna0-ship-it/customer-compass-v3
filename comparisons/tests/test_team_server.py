import pytest
from fastapi.testclient import TestClient
from lab_common.agent import CompanyNotFoundError, Recommendation
from lab_common.chat import UnavailableError
from lab_common.team import Decision, Outcome, create_team_app


class FakeTeam:
    approach = "fake"
    pattern = "supervisor"

    def __init__(self, error=None, stopped=False):
        self.error = error
        self.stopped = stopped
        self.calls = []

    def run(self, company, model):
        self.calls.append((company, model))
        if self.error:
            raise self.error
        decisions = [
            Decision(
                1, "code", ["crm_facts"], "crm_facts", "only one specialist is allowed", None, "top"
            )
        ]
        return Outcome(
            "stopped" if self.stopped else "completed",
            ["crm_facts"],
            decisions,
            1,
            None if self.stopped else Recommendation("Call Maya.", "Renewal open."),
            "done",
        )


def post(team, body=None, **kwargs):
    return TestClient(create_team_app(team)).post("/api/v1/multi-agent/run", json=body, **kwargs)


def test_health_names_the_approach_and_the_pattern():
    assert TestClient(create_team_app(FakeTeam())).get("/health").json() == {
        "status": "ok",
        "approach": "fake",
        "pattern": "supervisor",
    }


def test_a_run_answers_with_the_decisions_and_the_recommendation():
    team = FakeTeam()
    response = post(team, {"company": " Acme ", "model": "x/y"})
    assert response.status_code == 200
    assert response.json() == {
        "approach": "fake",
        "pattern": "supervisor",
        "status": "completed",
        "turns": 1,
        "specialists": ["crm_facts"],
        "decisions": [
            {
                "turn": 1,
                "decidedBy": "code",
                "allowed": ["crm_facts"],
                "chosen": "crm_facts",
                "reason": "only one specialist is allowed",
                "proposed": None,
                "level": "top",
            }
        ],
        "recommendation": {"action": "Call Maya.", "rationale": "Renewal open."},
        "message": "done",
    }
    assert team.calls == [("Acme", "x/y")]


def test_a_stopped_run_has_no_recommendation():
    assert "recommendation" not in post(FakeTeam(stopped=True), {"company": "Acme"}).json()


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ([], "The body must be a JSON object."),
        ({}, "company is required and must be a non-blank string."),
        ({"company": " "}, "company is required and must be a non-blank string."),
        ({"company": "x" * 201}, "company is limited to 200 characters."),
        ({"company": "x", "model": 5}, "model must be a string of at most 100 characters."),
    ],
)
def test_a_bad_request_is_422_with_a_short_detail(body, detail):
    response = post(FakeTeam(), body)
    assert (response.status_code, response.json()) == (422, {"detail": detail})


def test_invalid_json_is_422():
    response = TestClient(create_team_app(FakeTeam())).post(
        "/api/v1/multi-agent/run", content=b"{nope", headers={"Content-Type": "application/json"}
    )
    assert (response.status_code, response.json()) == (
        422,
        {"detail": "The body is not valid JSON."},
    )


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (CompanyNotFoundError("No company."), 404),
        (UnavailableError("The CRM could not be reached."), 503),
    ],
)
def test_the_errors_map_to_their_status(error, status):
    response = post(FakeTeam(error), {"company": "Acme"})
    assert response.status_code == status and response.json()["detail"] == str(error)


def test_anything_else_is_a_fixed_503_message():
    response = post(FakeTeam(RuntimeError("http://secret-host/leak")), {"company": "Acme"})
    assert response.status_code == 503 and "secret" not in response.text
