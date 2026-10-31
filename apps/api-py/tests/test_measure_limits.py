"""The limits-measuring script: its statistics and its collection logic, offline."""

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "evals"))

import measure_limits  # noqa: E402
import metrics  # noqa: E402


def test_percentile_uses_the_nearest_rank():
    data = [10, 20, 30, 40, 50]
    assert metrics.percentile(data, 50) == 30
    assert metrics.percentile(data, 90) == 50
    assert metrics.percentile(data, 20) == 10
    assert metrics.percentile([7], 99) == 7
    with pytest.raises(ValueError):
        metrics.percentile([], 50)


def test_round_up_to_a_step():
    assert metrics.round_up_to(61, 30) == 90 and metrics.round_up_to(60, 30) == 60


def run(
    case: str, seconds: float, status: str = "completed", steps: int = 8, calls=(2.0, 3.0, 4.0)
) -> dict:
    return {
        "case": case,
        "attempt": 1,
        "status": status,
        "error": None,
        "steps": steps,
        "agent_seconds": list(calls),
        "seconds": seconds,
    }


def test_summary_reports_how_close_runs_come_to_the_limits():
    rows = [run("a", 20), run("b", 40), run("c", 60), run("d", 100)]
    summary = measure_limits.summarise(rows, max_steps=8, timeout_seconds=180)
    assert summary["wall_seconds"] == {"p50": 40, "p90": 100, "max": 100}
    assert summary["share_of_timeout_used_at_p90"] == pytest.approx(0.56)
    assert summary["suggestion"]["timeout_seconds"] == 150  # 100 s plus 50%, rounded up to 30 s
    assert summary["trace_steps"]["max"] == 8


def test_failed_runs_are_counted_but_do_not_distort_the_timings():
    failed = {
        "case": "x",
        "attempt": 1,
        "status": None,
        "error": "HTTP 503",
        "steps": 0,
        "agent_seconds": [],
        "seconds": 0.1,
    }
    timed_out = run("t", 180, status="timed_out", steps=5)
    summary = measure_limits.summarise([run("a", 30), failed, timed_out], 8, 180)
    assert summary["errored"] == 1
    assert summary["statuses"] == {"completed": 1, "timed_out": 1}
    assert summary["wall_seconds"]["max"] == 30, "only completed runs set the timings"


def test_with_no_completed_run_there_is_no_suggestion():
    summary = measure_limits.summarise([run("t", 180, status="timed_out")], 8, 180)
    assert "suggestion" not in summary and summary["statuses"] == {"timed_out": 1}


def test_only_the_cases_that_run_the_whole_workflow_are_measured():
    cases = measure_limits.agent_cases()
    assert cases and all(
        c["expect_status"] == "completed" and c["expect_route"] == "agent" for c in cases
    )


@pytest.mark.asyncio
async def test_collection_reads_the_trace_and_survives_a_server_error():
    trace = [
        {"kind": "code", "duration_ms": 5},
        {"kind": "agent", "duration_ms": 2500},
        {"kind": "agent", "duration_ms": 4000},
        {"kind": "gate", "duration_ms": 1},
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 2:
            return httpx.Response(503, json={"error": "No model is configured."})
        assert json.loads(request.content)["message"]
        return httpx.Response(200, json={"status": "completed", "trace": trace})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await measure_limits.measure(
            client, "http://test", [{"id": "agent-01", "message": "Analyze Acme"}], runs=2
        )
    good, bad = rows
    assert (
        good["status"] == "completed" and good["steps"] == 4 and good["agent_seconds"] == [2.5, 4.0]
    )
    assert bad["error"] == "HTTP 503" and bad["steps"] == 0
