"""E3.3, offline: the supervisor-versus-pipeline comparison harness (evals/supervisor/compare_agents.py).

The table is worked by hand on a made-up recording, the recording step runs against a stand-in API on localhost, and
the cases are checked against the golden agent cases. No keys, no model, no stack. The real recording is a separate,
approved step (ADR 0035)."""

import http.server
import importlib.util
import json
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "compare_agents", ROOT / "evals" / "supervisor" / "compare_agents.py"
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

EVIDENCE = [
    {"label": "E1", "source": "crm: Acme Fabrication facts", "text": "facts"},
    {"label": "E2", "source": "document: [agri-supply] Sprayer calibration", "text": "farm text"},
]
GUARD = {"flagged": False, "reasons": []}


def completed(supervisor: dict | None = None, llm_calls: int = 3) -> dict:
    body = {
        "route": "agent",
        "status": "completed",
        "company": {"id": 1, "name": "Acme Fabrication"},
        "evidence": EVIDENCE,
        "recommendation": {"action": "a", "rationale": "r", "evidence": ["E1"]},
        "review": {"approved": True, "verdict": "approve", "reasons": [], "revisions": 0},
        "proposedTask": {"companyName": "Acme Fabrication", "note": "n"},
        "guardrail": GUARD,
        "llmCalls": [{}] * llm_calls,
    }
    if supervisor:
        body["supervisor"] = supervisor
    return body


SUPERVISOR = {
    "turns": [
        {
            "turn": 1,
            "next": "crm_facts",
            "source": "code",
            "reason": "only choice",
            "allowed": ["crm_facts"],
        },
        {
            "turn": 2,
            "next": "researcher",
            "source": "supervisor",
            "reason": "more background",
            "query": "sprayer",
        },
        {
            "turn": 3,
            "next": "analyst",
            "source": "supervisor",
            "reason": "x",
            "proposed": "reviewer",
        },
    ],
    "modelDecisions": 2,
    "codeDecisions": 1,
}
DIRECT = {"route": "direct", "message": "This looks like a simple question."}
ANSWERED = {
    "route": "agent",
    "status": "answered",
    "message": "Manufacturing.",
    "grounded": True,
    "evidence": EVIDENCE[:1],
    "citations": EVIDENCE[:1],
    "guardrail": GUARD,
    "llmCalls": [{}],
    "trace": [],
    "supervisor": {
        "turns": [{"turn": 1, "next": "crm_facts", "source": "code", "reason": "only"}],
        "modelDecisions": 0,
        "codeDecisions": 1,
    },
}


def run(body: dict, ms: float = 1000, tasks_changed: bool = False) -> dict:
    return mod.compact(body, ms, tasks_changed)


@pytest.fixture
def two_cases(monkeypatch):
    cases = [c for c in mod.CASES if c["id"] in ("agent-01", "agent-08")]
    monkeypatch.setattr(mod, "CASES", cases)
    return cases


def made_up() -> dict:
    runs = {"pipeline": {}, "supervisor": {}}
    for rep in (1, 2):
        runs["pipeline"][f"agent-01#{rep}"] = run(completed(), 2000)
        runs["pipeline"][f"agent-08#{rep}"] = run(DIRECT, 10)
        runs["supervisor"][f"agent-01#{rep}"] = run(completed(SUPERVISOR, 5), 3000)
        runs["supervisor"][f"agent-08#{rep}"] = run(ANSWERED, 1000)
    return {
        "meta": {
            "model": "made-up",
            "embedding_model": "made-up",
            "recorded": "2026-11-14",
            "repeats": 2,
        },
        "runs": runs,
    }


# ------------------------------------------------------------------------------------------------ the cases


def test_the_ten_cases_are_the_golden_agent_cases():
    golden = json.loads((ROOT / "evals" / "golden" / "agent.json").read_text())
    assert [c["id"] for c in mod.CASES] == [g["id"] for g in golden]
    assert [c["message"] for c in mod.CASES] == [g["message"] for g in golden]
    assert [c["expect_company"] for c in mod.CASES] == [g["expect_company"] for g in golden]
    for case in mod.CASES:
        assert {"expect_pipeline", "expect_supervisor"} <= set(case)


def test_the_supervisor_is_expected_to_answer_the_question_case_and_the_pipeline_to_send_it_away():
    case = next(c for c in mod.CASES if c["id"] == "agent-08")
    assert (case["expect_pipeline"], case["expect_supervisor"]) == ("direct", "answered")


# ------------------------------------------------------------------------------------------------ one run, compacted


def test_a_completed_pipeline_run_is_compacted():
    r = run(completed())
    assert (r["status"], r["company"], r["model_calls"], r["evidence_items"]) == (
        "completed",
        "Acme Fabrication",
        3,
        2,
    )
    assert (
        r["farm_supply_items"] == 1
        and r["valid_citations"]
        and r["approved"]
        and not r["tasks_changed"]
    )
    assert "turns" not in r


def test_a_citation_of_a_label_that_does_not_exist_is_not_valid():
    body = completed()
    body["recommendation"]["evidence"] = ["E1", "E9"]
    assert run(body)["valid_citations"] is False


def test_a_supervised_run_counts_its_decisions_overrides_and_own_queries():
    r = run(completed(SUPERVISOR, 5))
    assert (
        r["turns"],
        r["model_decisions"],
        r["overrides"],
        r["researcher_runs"],
        r["own_queries"],
    ) == (3, 2, 1, 1, 1)


def test_an_unreadable_supervisor_answer_counts_as_an_override():
    sup = {
        "turns": [
            {
                "turn": 1,
                "next": "analyst",
                "source": "code",
                "reason": "the supervisor's answer could not be read; the pipeline's next step was used",
            }
        ],
        "modelDecisions": 0,
    }
    assert run(completed(sup))["overrides"] == 1


def test_the_direct_route_and_an_answered_question_are_recorded_by_their_status():
    assert run(DIRECT)["status"] == "direct" and run(DIRECT)["model_calls"] == 0
    answered = run(ANSWERED)
    assert (
        answered["status"] == "answered"
        and answered["valid_citations"] is False
        and answered["model_calls"] == 1
    )


# ------------------------------------------------------------------------------------------------ the table, by hand


def test_the_table_matches_the_hand_worked_numbers(two_cases):
    t = mod.table(made_up())
    p, s = t["pipeline"], t["supervisor"]
    # 2 cases x 2 repeats = 4 runs per arm; every run is what its case expects (agent-01 completed, agent-08 direct / answered)
    assert (p["runs"], p["as_expected"], p["completed"]) == (4, 4, 2)
    assert (s["runs"], s["as_expected"], s["completed"]) == (4, 4, 2)
    assert (
        p["completed_valid_citations"],
        p["completed_approved"],
        p["tasks_written"],
        p["flagged"],
    ) == (2, 2, 0, 0)
    assert p["model_calls_total"] == 6 and p["model_calls_per_completed"] == 3
    assert (
        s["model_calls_total"] == 12 and s["model_calls_per_completed"] == 5
    )  # (5 + 5 + 1 + 1) / 4 runs, completed ones 5 each
    assert p["farm_supply_items_in_completed"] == 2 and s["farm_supply_items_in_completed"] == 2
    assert p["median_ms"] == 1005  # 10, 10, 2000, 2000
    assert (
        s["model_decisions_total"],
        s["overrides_by_code"],
        s["runs_with_research"],
        s["own_search_queries"],
    ) == (4, 2, 2, 2)
    assert s["supervisor_turns_per_run"] == 2.0  # (3 + 3 + 1 + 1) / 4


def test_a_run_that_wrongly_changed_the_task_table_is_counted(two_cases):
    data = made_up()
    data["runs"]["supervisor"]["agent-01#1"] = run(
        completed(SUPERVISOR, 5), 3000, tasks_changed=True
    )
    assert mod.table(data)["supervisor"]["tasks_written"] == 1


def test_a_failed_request_is_counted_and_left_out_of_the_rows(two_cases):
    data = made_up()
    data["runs"]["pipeline"]["agent-01#2"] = {"ok": False, "status": 503, "error": "no key"}
    p = mod.table(data)["pipeline"]
    assert (p["failed"], p["runs"]) == (1, 3)


def test_the_table_prints(two_cases, capsys):
    mod.show(mod.table(made_up()), made_up())
    out = capsys.readouterr().out
    assert (
        "pipeline" in out
        and "supervisor" in out
        and "tasks written before a confirm (must be 0)" in out
    )


# ------------------------------------------------------------------------------------------------ replay and check


def test_nothing_recorded_exits_with_2(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "RECORDED", tmp_path / "none.json")
    assert mod.main([]) == 2


def test_write_baseline_then_check_passes_and_a_changed_count_fails(
    tmp_path, monkeypatch, two_cases
):
    recorded, baseline = tmp_path / "recorded.json", tmp_path / "baseline.json"
    recorded.write_text(json.dumps(made_up()))
    monkeypatch.setattr(mod, "RECORDED", recorded)
    monkeypatch.setattr(mod, "BASELINE", baseline)
    assert mod.main(["--write-baseline"]) == 0
    assert mod.main(["--check"]) == 0
    data = made_up()
    data["runs"]["supervisor"]["agent-01#1"] = run(
        completed(SUPERVISOR, 9), 3000
    )  # one more model call
    recorded.write_text(json.dumps(data))
    assert mod.main(["--check"]) == 1


def test_check_without_a_baseline_fails_and_says_so(tmp_path, monkeypatch, two_cases, capsys):
    recorded = tmp_path / "recorded.json"
    recorded.write_text(json.dumps(made_up()))
    monkeypatch.setattr(mod, "RECORDED", recorded)
    monkeypatch.setattr(mod, "BASELINE", tmp_path / "missing.json")
    assert mod.main(["--check"]) == 1
    assert "no baseline.json yet" in capsys.readouterr().err


def test_latency_does_not_enter_the_baseline(two_cases):
    assert not {"median_ms", "p95_ms"} & set(mod.stable(mod.table(made_up()))["pipeline"])


# ------------------------------------------------------------------------------------------------ the recording step


class StandInApi:
    """A tiny API on localhost: /api/v1/tasks, /agent/recommend, /agent/supervise, with canned bodies shaped like the real ones."""

    def __init__(self, fail_first: int = 0, write_task: bool = False):
        self.posts: list[str] = []
        self.tasks = 0
        self.fail_first = fail_first
        self.write_task = write_task
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _send(self, status: int, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(200, [{"id": i} for i in range(outer.tasks)])

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length))
                outer.posts.append(self.path)
                if outer.fail_first > 0:
                    outer.fail_first -= 1
                    return self._send(503, {"detail": "busy"})
                if outer.write_task:
                    outer.tasks += 1
                direct = "industry" in payload["message"]
                if self.path.endswith("/recommend"):
                    return self._send(200, DIRECT if direct else completed())
                self._send(200, ANSWERED if direct else completed(SUPERVISOR, 5))

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def one_repeat(monkeypatch, tmp_path, two_cases):
    monkeypatch.setattr(mod, "REPEATS", 1)
    monkeypatch.setattr(mod, "RECORDED", tmp_path / "recorded.json")
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    monkeypatch.setenv("MODEL", "a-model")
    monkeypatch.setenv("EMBEDDING_MODEL", "an-embedding-model")


def test_record_asks_both_arms_for_every_case_and_labels_the_recording(one_repeat, monkeypatch):
    api = StandInApi()
    monkeypatch.setenv("API_URL", api.url)
    try:
        assert mod.record() == 0
    finally:
        api.close()
    data = json.loads(mod.RECORDED.read_text())
    assert (
        data["meta"]["model"] == "a-model"
        and data["meta"]["embedding_model"] == "an-embedding-model"
    )
    assert sorted(data["runs"]["pipeline"]) == ["agent-01#1", "agent-08#1"]
    assert sorted(data["runs"]["supervisor"]) == ["agent-01#1", "agent-08#1"]
    assert data["runs"]["supervisor"]["agent-08#1"]["status"] == "answered"
    assert data["runs"]["pipeline"]["agent-08#1"]["status"] == "direct"
    assert not any(r["tasks_changed"] for arm in data["runs"].values() for r in arm.values())
    assert len(api.posts) == 4  # 2 cases x 1 repeat x 2 arms


def test_record_resumes_without_asking_again_for_what_is_recorded(one_repeat, monkeypatch):
    api = StandInApi()
    monkeypatch.setenv("API_URL", api.url)
    try:
        mod.record()
        asked = len(api.posts)
        mod.record()
        assert len(api.posts) == asked
    finally:
        api.close()


def test_record_retries_a_rate_limited_call(one_repeat, monkeypatch):
    api = StandInApi(fail_first=2)
    monkeypatch.setenv("API_URL", api.url)
    try:
        mod.record()
    finally:
        api.close()
    data = json.loads(mod.RECORDED.read_text())
    assert all(r["ok"] for arm in data["runs"].values() for r in arm.values())
    assert len(api.posts) == 6  # 4 runs + 2 failed attempts


def test_record_notices_a_run_that_wrote_a_task(one_repeat, monkeypatch):
    api = StandInApi(write_task=True)
    monkeypatch.setenv("API_URL", api.url)
    try:
        mod.record()
    finally:
        api.close()
    data = json.loads(mod.RECORDED.read_text())
    assert all(r["tasks_changed"] for arm in data["runs"].values() for r in arm.values())
    assert mod.table(data)["pipeline"]["tasks_written"] == 2
