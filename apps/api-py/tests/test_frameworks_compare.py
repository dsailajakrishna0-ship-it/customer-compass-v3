"""Stage 5.5, offline: the comparison's metrics, its tables and the committed recordings replaying to the
committed baseline. No keys, network, running stack or framework packages needed."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVALS = ROOT / "evals"
sys.path.insert(0, str(EVALS))

import compare_frameworks as cf  # noqa: E402


def test_code_lines_ignore_blanks_comments_and_docstrings():
    source = '''
def f(x):
    """Docstring
    over two lines."""

    # a comment
    y = x + 1
    return y
'''
    assert cf.code_lines(source) == 3  # def, y =, return


def test_the_ranking_metrics_use_the_golden_set():
    golden = json.loads(cf.GOLDEN_RETRIEVAL.read_text())
    perfect = {c["id"]: c["relevant"] for c in golden}
    result = cf._ranking_metrics(perfect)
    assert result["recall_at_1"] <= 1.0 and result["recall_at_5"] == 1.0 and result["mrr"] == 1.0
    assert (
        result["unanswerable_declined"] == 6.0
    )  # nothing is returned for an unanswerable question

    nothing = cf._ranking_metrics({})
    assert nothing["recall_at_5"] == 0.0 and nothing["mrr"] == 0.0


def test_the_agent_table_counts_what_a_caller_can_see():
    def run(**kw):
        base = {
            "status": "completed", "as_expected": True, "citations_valid": True, "approved": True,
            "revisions": 0, "evidence_n": 5, "evidence_steps": 3, "model_calls": 4,
            "tokens_in": 1000, "tokens_out": 100, "wall_ms": 100, "tasks_written": 0,
            "fallback_used": False,
        }  # fmt: skip
        return {**base, **kw}

    data = {
        "impls": {
            "manual": [run(), run(revisions=1)],
            "frameworks": [
                run(citations_valid=False, approved=False),
                run(status="http_503", as_expected=False),
            ],
        }
    }
    table = cf.agent_table(data)
    assert table["manual"]["valid_citations"] == 2 and table["manual"]["revisions_mean"] == 0.5
    assert table["frameworks"]["completed"] == 1 and table["frameworks"]["valid_citations"] == 0
    assert table["frameworks"]["outcome_as_expected"] == 1
    assert table["manual"]["tasks_written_by_recommend"] == 0


def test_the_committed_recordings_cover_every_seam_and_both_sides():
    for seam in ("chunker", "retrieval", "agent"):
        assert (cf.DATA / f"{seam}.json").exists(), seam
    tables = cf.all_tables()
    for seam in ("chunker", "retrieval", "agent"):
        assert set(tables[seam]) == {"manual", "frameworks"}


def test_the_committed_recordings_replay_to_the_committed_baseline():
    assert cf.check(cf.all_tables()) == []


def test_a_changed_number_fails_the_check(monkeypatch):
    tables = cf.all_tables()
    tables["agent"]["frameworks"]["valid_citations"] += 1
    problems = cf.check(tables)
    assert problems and "valid_citations" in problems[0]


def test_both_sides_never_let_recommend_write_a_task():
    """The confirm gate is the same on both sides: recommending writes nothing, in every recorded run."""
    tables = cf.all_tables()
    assert tables["agent"]["manual"]["tasks_written_by_recommend"] == 0
    assert tables["agent"]["frameworks"]["tasks_written_by_recommend"] == 0


def test_the_retrieval_recording_shows_identical_chunks_on_both_sides():
    table = cf.retrieval_table(cf._load(cf.DATA / "retrieval.json"))
    assert table["frameworks"]["same_chunks_as_manual"] == table["frameworks"]["questions"]


def test_lines_of_code_are_counted_for_every_seam():
    loc = cf.lines_of_code()
    assert set(loc) == {"chunker", "retrieval", "agent"}
    assert all(side > 0 for seam in loc.values() for side in seam.values())


def test_the_replay_script_runs_offline_and_exits_zero():
    out = subprocess.run(
        [sys.executable, str(EVALS / "compare_frameworks.py"), "--check"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "apps" / "api-py")},
    )
    assert out.returncode == 0, out.stderr
    assert "OK: every number matches" in out.stdout
