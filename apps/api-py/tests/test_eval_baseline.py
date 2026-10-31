"""Offline checks for the V3 evaluation baseline: scoring maths, golden-set integrity, and the
baseline comparison. No stack, keys or models are needed (the live suites run via `just eval`)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
EVALS = ROOT / "evals"
sys.path.insert(0, str(EVALS))

import metrics  # noqa: E402
import run_eval  # noqa: E402

DOCS = {p.name for p in (ROOT / "sample-data" / "documents").glob("*.md")}
SEED = (ROOT / "apps" / "api-py" / "migrations" / "versions" / "0002_demo_seed_data.py").read_text()
TOOLS = {"get_company_summary", "get_open_deals", "search_documents", "create_followup_task"}


def golden(name: str) -> list[dict]:
    return json.loads((EVALS / "golden" / name).read_text())


# ------------------------------------------------------------------ the maths


def test_recall_at_k_counts_relevant_documents_in_the_top_k():
    ranked = ["a", "b", "c", "d"]
    assert metrics.recall_at_k(ranked, {"a", "d"}, 1) == 0.5
    assert metrics.recall_at_k(ranked, {"a", "d"}, 3) == 0.5
    assert metrics.recall_at_k(ranked, {"a", "d"}, 4) == 1.0
    assert metrics.recall_at_k([], {"a"}, 5) == 0.0


def test_recall_needs_a_relevant_document():
    with pytest.raises(ValueError):
        metrics.recall_at_k(["a"], set(), 1)


def test_reciprocal_rank_is_one_over_the_first_hit():
    assert metrics.reciprocal_rank(["x", "a", "b"], {"a", "b"}) == 0.5
    assert metrics.reciprocal_rank(["a"], {"a"}) == 1.0
    assert metrics.reciprocal_rank(["x", "y"], {"a"}) == 0.0


def test_chunks_from_one_document_count_once_at_their_best_rank():
    assert metrics.dedupe_keep_order(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_tolerance_is_an_absolute_band():
    assert metrics.within_tolerance(0.80, 0.82, 0.02)
    assert not metrics.within_tolerance(0.80, 0.83, 0.02)
    assert metrics.within_tolerance(0.5, 0.5, 0.0)


# --------------------------------------------------------------- golden sets


def test_retrieval_set_has_30_to_50_answerable_questions():
    cases = golden("retrieval.json")
    answerable = [c for c in cases if c["relevant"]]
    assert 30 <= len(answerable) <= 50
    assert [c for c in cases if not c["relevant"]], "keep some unanswerable questions"
    assert len({c["id"] for c in cases}) == len(cases)


def test_every_relevant_document_exists_in_the_sample_data():
    for case in golden("retrieval.json"):
        assert set(case["relevant"]) <= DOCS, case["id"]


def test_scoped_questions_name_a_seeded_company():
    for case in golden("retrieval.json"):
        if case["company"]:
            assert f"'{case['company']}'" in SEED, case["id"]


def test_tool_call_set_has_ten_cases_and_known_tools():
    cases = golden("tool_calls.json")
    assert len(cases) == 10
    assert {c["expect_tool"] for c in cases} <= TOOLS | {None}
    assert len({c["id"] for c in cases}) == 10


def test_agent_set_has_ten_cases():
    cases = golden("agent.json")
    assert len(cases) == 10
    assert {c["expect_route"] for c in cases} <= {"agent", "direct"}


def test_adversarial_set_has_at_least_twenty_attacks_and_some_benign_prompts():
    cases = json.loads((EVALS / "adversarial-prompts.json").read_text())
    assert sum(c["is_attack"] for c in cases) >= 20
    assert any(not c["is_attack"] for c in cases)


# ------------------------------------------------------- runner, offline parts


def test_adversarial_suite_matches_the_recorded_rule_expectations():
    cases = json.loads((EVALS / "adversarial-prompts.json").read_text())
    attacks = [c for c in cases if c["is_attack"]]
    expected_rate = sum(c["rules_catch"] for c in attacks) / len(attacks)
    result = run_eval.run_adversarial()["metrics"]
    assert result["attack_detection_rate"] == pytest.approx(expected_rate)
    assert result["false_positive_rate"] == 0.0


LEGACY_ENV = {"llm_provider": "ollama", "ollama_model": "qwen2.5:3b"}  # how v2.json was recorded


def test_a_report_from_before_cloud_only_names_its_local_model():
    assert run_eval.chat_model_of(LEGACY_ENV) == "ollama/qwen2.5:3b"
    assert run_eval.chat_model_of({"chat_model": "openrouter/x:free"}) == "openrouter/x:free"


def test_model_dependent_suites_are_dropped_when_the_chat_model_changed():
    now = {"chat_model": "openrouter/google/gemma-4-31b-it:free"}
    suites, note = run_eval.comparable_suites(LEGACY_ENV, now, list(run_eval.SUITES))
    assert suites == ["adversarial", "retrieval"]
    assert "tools, agent" in note and "ollama/qwen2.5:3b" in note and "gemma-4-31b" in note


def test_every_suite_is_kept_when_the_chat_model_is_the_same():
    env = {"chat_model": "openrouter/x:free"}
    suites, note = run_eval.comparable_suites(env, env, list(run_eval.SUITES))
    assert suites == list(run_eval.SUITES) and note is None


def test_no_note_when_there_were_no_model_dependent_suites_to_drop():
    suites, note = run_eval.comparable_suites(LEGACY_ENV, {"chat_model": "z"}, ["retrieval"])
    assert suites == ["retrieval"] and note is None


def _report(**suite_metrics) -> dict:
    return {"tolerances": {"retrieval": 0.02}, "suites": {"retrieval": {"metrics": suite_metrics}}}


def test_compare_accepts_values_inside_the_tolerance():
    assert run_eval.compare(_report(mrr=0.80), _report(mrr=0.81)) == []


def test_compare_reports_values_outside_the_tolerance():
    problems = run_eval.compare(_report(mrr=0.80), _report(mrr=0.70))
    assert len(problems) == 1 and "retrieval.mrr" in problems[0]


def test_compare_ignores_speed_and_size_numbers():
    assert run_eval.compare(_report(mean_latency_s=10.0), _report(mean_latency_s=99.0)) == []


def test_compare_flags_a_suite_missing_from_the_baseline():
    current = _report(mrr=0.8)
    baseline = {"tolerances": {}, "suites": {}}
    assert run_eval.compare(baseline, current) == ["retrieval: not in the baseline"]


# ----------------------------------------------------------- the saved baseline


def test_saved_baseline_covers_every_suite():
    baseline = json.loads((EVALS / "baseline" / "v2.json").read_text())
    assert set(baseline["suites"]) == set(run_eval.SUITES)
    assert baseline["environment"]["embedding_model"]


def test_saved_adversarial_baseline_still_matches_the_guard():
    """The guard is deterministic: if its rules change, the baseline must be re-taken on purpose."""
    baseline = json.loads((EVALS / "baseline" / "v2.json").read_text())
    current = run_eval.run_adversarial()
    assert run_eval.compare(baseline, {"suites": {"adversarial": current}}) == []
