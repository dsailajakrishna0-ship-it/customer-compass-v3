"""Stage 5.2, offline: the judge's cache and retry plumbing, the reply parser, the metrics table, and
the judged golden set. No keys, network or DeepEval are needed (DeepEval is only installed for
`just eval-judged`)."""

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
EVALS = ROOT / "evals"
sys.path.insert(0, str(EVALS))

import judge as j  # noqa: E402
import run_judged  # noqa: E402


class FakePost:
    """Stands in for httpx.post: returns the queued replies in order and counts the calls."""

    def __init__(self, *replies: httpx.Response) -> None:
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, *_args, **_kwargs) -> httpx.Response:
        self.calls += 1
        return self.replies.pop(0)


def ok(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def make_judge(tmp_path: Path, mode: str = "record", post=None) -> j.Judge:
    return j.Judge(
        mode=mode,
        cache=j.JudgeCache(tmp_path / "cache.jsonl"),
        api_key="test-key-not-real",
        post=post,
        sleep=lambda _s: None,
    )


# ------------------------------------------------------------------ cache key and cache file


def test_cache_key_changes_with_model_version_and_prompt():
    base = j.cache_key("m", "v1", "p")
    assert base == j.cache_key("m", "v1", "p")
    assert (
        len(
            {
                base,
                j.cache_key("m2", "v1", "p"),
                j.cache_key("m", "v2", "p"),
                j.cache_key("m", "v1", "q"),
            }
        )
        == 4
    )


def test_cache_key_does_not_confuse_field_boundaries():
    assert j.cache_key("ab", "c", "d") != j.cache_key("a", "bc", "d")


def test_cache_survives_a_reload(tmp_path):
    cache = j.JudgeCache(tmp_path / "c.jsonl")
    cache.put("k1", "m", "v", '{"a": 1}')
    assert j.JudgeCache(tmp_path / "c.jsonl").get("k1") == '{"a": 1}'
    assert j.JudgeCache(tmp_path / "c.jsonl").get("missing") is None


def test_cache_stores_hashes_and_answers_not_prompts(tmp_path):
    judge = make_judge(tmp_path, post=FakePost(ok('{"v": 1}')))
    judge.complete("secret-looking prompt text")
    assert "secret-looking" not in (tmp_path / "cache.jsonl").read_text()


# ---------------------------------------------------------------------------- reply parser


@pytest.mark.parametrize(
    "text",
    [
        '{"verdict": "yes"}',
        '```json\n{"verdict": "yes"}\n```',
        'Sure! Here you go:\n{"verdict": "yes"}\nHope that helps.',
    ],
)
def test_extract_json_copes_with_fences_and_chatter(text):
    assert j.extract_json(text) == {"verdict": "yes"}


@pytest.mark.parametrize("text", ["no json here", '{"broken": ', ""])
def test_extract_json_rejects_garbage(text):
    with pytest.raises(ValueError):
        j.extract_json(text)


# --------------------------------------------------------------------- replay and record


def test_replay_never_touches_the_network_and_stops_on_a_miss(tmp_path):
    post = FakePost()
    judge = make_judge(tmp_path, mode="replay", post=post)
    with pytest.raises(j.ReplayMiss):
        judge.complete("never recorded")
    assert post.calls == 0


def test_record_calls_once_then_replay_gives_the_same_answer(tmp_path):
    post = FakePost(ok('{"v": 1}'))
    recorder = make_judge(tmp_path, post=post)
    assert recorder.complete("prompt") == '{"v": 1}'
    assert recorder.complete("prompt") == '{"v": 1}'  # second time: from the cache
    assert post.calls == 1
    assert [c["cached"] for c in recorder.calls] == [False, True]

    replayer = make_judge(tmp_path, mode="replay", post=FakePost())
    assert replayer.complete("prompt") == '{"v": 1}'
    assert replayer.fresh_calls == 0


def test_a_new_judge_model_does_not_reuse_old_recordings(tmp_path):
    make_judge(tmp_path, post=FakePost(ok("{}"))).complete("prompt")
    other = j.Judge(
        mode="replay", cache=j.JudgeCache(tmp_path / "cache.jsonl"), model="another/model"
    )
    with pytest.raises(j.ReplayMiss):
        other.complete("prompt")


def test_record_retries_a_rate_limit_and_records_nothing_when_it_gives_up(tmp_path):
    limited = httpx.Response(429)
    post = FakePost(limited, ok('{"v": 2}'))
    assert make_judge(tmp_path, post=post).complete("p") == '{"v": 2}'
    assert post.calls == 2

    post = FakePost(*[httpx.Response(429)] * j.MAX_ATTEMPTS)
    judge = make_judge(tmp_path / "x", post=post)
    with pytest.raises(j.JudgeUnavailable):
        judge.complete("other prompt")
    assert post.calls == j.MAX_ATTEMPTS
    assert judge.cache.entries == {}


def test_record_stops_at_once_on_the_daily_free_limit(tmp_path):
    daily = httpx.Response(
        429, json={"error": {"message": "Rate limit exceeded: free-models-per-day"}}
    )
    post = FakePost(daily)
    with pytest.raises(j.JudgeUnavailable, match="daily"):
        make_judge(tmp_path, post=post).complete("p")
    assert post.calls == 1  # no pointless retries


def test_record_does_not_retry_a_rejected_key(tmp_path):
    post = FakePost(httpx.Response(401))
    with pytest.raises(j.JudgeUnavailable):
        make_judge(tmp_path, post=post).complete("p")
    assert post.calls == 1


def test_record_mode_needs_a_key():
    with pytest.raises(ValueError):
        j.Judge(mode="record", api_key="")


# --------------------------------------------------------------------------- the report

CASES = [
    {"id": "a", "scores": {"faithfulness": 1.0, "answer_relevancy": 0.5}},
    {"id": "b", "scores": {"faithfulness": 0.5, "answer_relevancy": 0.5}},
    {"id": "c", "scores": {}, "error": "ReplayMiss"},
]


def test_summarise_averages_scored_cases_and_counts_errors():
    out = j.summarise(CASES)
    assert out["faithfulness"] == 0.75
    assert out["answer_relevancy"] == 0.5
    assert out["context_precision"] is None
    assert (out["cases"], out["errored_cases"]) == (3, 1)


def test_compare_flags_only_moves_beyond_the_tolerance():
    base = {"faithfulness": 0.8, "answer_relevancy": 0.8, "context_precision": None}
    assert j.compare(base, {"faithfulness": 0.7, "answer_relevancy": 0.8}) == []
    problems = j.compare(base, {"faithfulness": 0.5, "answer_relevancy": None})
    assert len(problems) == 2 and "faithfulness" in problems[0] and "no score" in problems[1]


def test_table_shows_branch_header_baseline_delta_and_v2_retrieval():
    current = j.summarise(CASES)
    table = j.format_table(
        current,
        {"faithfulness": 0.8},
        {"recall_at_1": 0.7, "mrr": 0.8},
        "judged evals  branch feat/x @ abc123",
    )
    assert "branch feat/x @ abc123" in table
    row = next(line for line in table.splitlines() if line.startswith("faithfulness"))
    assert row.split() == ["faithfulness", "0.800", "0.750", "-0.050"]
    assert "-" in next(line for line in table.splitlines() if line.startswith("context_precision"))
    assert "recall_at_1" in table and "mrr" in table


# -------------------------------------------------------------------------- the runner


def test_judge_cases_isolates_errors_and_stops_after_the_judge_is_unavailable(tmp_path):
    cases = [{"id": i, "question": "q", "reference": "r"} for i in ("ok", "bad", "down", "late")]
    subjects = {i: {"answer": "a", "contexts": ["c"]} for i in ("ok", "bad", "down", "late")}

    def scorer(_judge, case):
        if case["id"] == "bad":
            raise ValueError("not JSON")
        if case["id"] == "down":
            raise j.JudgeUnavailable("HTTP 429")
        return {"faithfulness": 1.0}

    judge = make_judge(tmp_path, mode="replay")
    rows = {r["id"]: r for r in run_judged.judge_cases(cases, subjects, judge, scorer)}
    assert rows["ok"]["scores"] == {"faithfulness": 1.0} and "error" not in rows["ok"]
    assert "ValueError" in rows["bad"]["error"]
    assert "429" in rows["down"]["error"] and "skipped" in rows["late"]["error"]


def test_judge_cases_flags_missing_subjects_and_empty_context(tmp_path):
    cases = [{"id": "x"}, {"id": "y"}]
    rows = run_judged.judge_cases(
        cases, {"y": {"answer": "a", "contexts": []}}, make_judge(tmp_path, "replay"), lambda *_: {}
    )
    assert "no recorded answer" in rows[0]["error"]
    assert "no retrieved context" in rows[1]["error"]


# ----------------------------------------------------------------- the files in the repo


def test_judged_golden_set_points_at_real_retrieval_cases_and_has_references():
    judged = json.loads((EVALS / "golden" / "judged.json").read_text())
    retrieval = {c["id"]: c for c in json.loads((EVALS / "golden" / "retrieval.json").read_text())}
    pending = json.loads((EVALS / "golden" / "judged-pending.json").read_text())
    assert 2 <= len(judged) <= 8  # small on purpose: every case costs 7 to 10 judge calls
    # cases written but not recorded yet (the free tier's daily limit ran out); move them into judged.json
    assert not {c["id"] for c in judged} & {c["id"] for c in pending}
    for case in judged + pending:
        assert case["question"] == retrieval[case["id"]]["question"]
        assert retrieval[case["id"]]["relevant"], "judge only answerable questions"
        assert case["reference"].strip()


def test_the_core_judge_module_does_not_need_deepeval():
    source = (EVALS / "judge.py").read_text() + (EVALS / "run_judged.py").read_text().split(
        "def main"
    )[0]
    assert "import deepeval" not in source and "from deepeval" not in source


def test_recorded_cache_and_subjects_are_consistent_with_the_pins():
    cache = j.JudgeCache()
    for row in cache.entries.values():
        assert row["model"] == j.JUDGE_MODEL and row["prompt_version"] == j.JUDGE_PROMPT_VERSION
    subjects = run_judged.load_subjects()
    judged_ids = {c["id"] for c in json.loads((EVALS / "golden" / "judged.json").read_text())}
    assert set(subjects) <= judged_ids
