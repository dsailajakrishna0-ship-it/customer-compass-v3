"""Stage 5.4, offline: the comparison harness's cache, snapshots, metrics and table, and the committed
recordings replaying to the committed baseline. No keys, network or running stack needed."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
EVALS = ROOT / "evals"
sys.path.insert(0, str(EVALS))

import agentic_lib as lib  # noqa: E402


class FakePost:
    def __init__(self, *replies: httpx.Response):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, *_a, **_k) -> httpx.Response:
        self.calls += 1
        return self.replies.pop(0)


def ok(text: str, tin: int = 11, tout: int = 4) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": tin, "completion_tokens": tout},
        },
    )


def recorder(tmp_path: Path, mode="record", post=None) -> lib.Recorder:
    return lib.Recorder(
        mode=mode,
        cache=lib.CallCache(tmp_path / "cache.jsonl"),
        api_key="test-key-not-real",
        post=post,
        sleep=lambda _s: None,
    )


# ------------------------------------------------------------------------------------ cache and keys


def test_the_cache_key_changes_with_every_part():
    base = lib.cache_key("r", "m", "v", "s", "u")
    assert base == lib.cache_key("r", "m", "v", "s", "u")
    for changed in (
        lib.cache_key("r2", "m", "v", "s", "u"),
        lib.cache_key("r", "m2", "v", "s", "u"),
        lib.cache_key("r", "m", "v2", "s", "u"),
        lib.cache_key("r", "m", "v", "s2", "u"),
        lib.cache_key("r", "m", "v", "s", "u2"),
    ):
        assert changed != base
    assert lib.cache_key("ab", "c", "v", "s", "u") != lib.cache_key("a", "bc", "v", "s", "u")


def test_a_search_key_depends_on_query_company_size_and_mode():
    base = lib.snapshot_key("q", None, 4, "hybrid")
    assert base != lib.snapshot_key("q2", None, 4, "hybrid")
    assert base != lib.snapshot_key("q", "Acme", 4, "hybrid")
    assert base != lib.snapshot_key("q", None, 10, "hybrid")
    assert base != lib.snapshot_key("q", None, 4, "dense")


def test_record_saves_tokens_and_latency_and_the_second_call_is_free(tmp_path):
    post = FakePost(ok("hello", 20, 5))
    rec = recorder(tmp_path, post=post)

    first = rec.call("answer", "sys", "user")
    second = rec.call("answer", "sys", "user")

    assert (first.content, first.tokens_in, first.tokens_out) == ("hello", 20, 5)
    assert second == first and post.calls == 1 and rec.fresh_calls == 1
    row = json.loads((tmp_path / "cache.jsonl").read_text().splitlines()[0])
    assert set(row) == {
        "sha256", "role", "model", "version", "content", "tokens_in", "tokens_out", "latency_ms",
    }  # fmt: skip


def test_the_cache_file_never_holds_a_field_called_key(tmp_path):
    rec = recorder(tmp_path, post=FakePost(ok("x")))
    rec.call("answer", "s", "u")
    assert '"key"' not in (tmp_path / "cache.jsonl").read_text()


def test_replay_never_touches_the_network_and_a_miss_stops_the_run(tmp_path):
    post = FakePost()
    rec = recorder(tmp_path, mode="replay", post=post)
    with pytest.raises(lib.ReplayMiss):
        rec.call("relevance", "s", "u")
    assert post.calls == 0


def test_replay_reads_what_record_saved(tmp_path):
    recorder(tmp_path, post=FakePost(ok("saved"))).call("answer", "s", "u")
    again = recorder(tmp_path, mode="replay", post=FakePost()).call("answer", "s", "u")
    assert again.content == "saved"


def test_a_rate_limit_is_retried_and_a_bad_request_is_not(tmp_path):
    post = FakePost(httpx.Response(429, json={}), ok("fine"))
    assert recorder(tmp_path, post=post).call("a", "s", "u").content == "fine"
    bad = FakePost(httpx.Response(400, json={}))
    with pytest.raises(lib.RecordFailed):
        recorder(tmp_path / "x", post=bad).call("a", "s", "u")
    assert bad.calls == 1


def test_record_mode_needs_a_key(tmp_path):
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        lib.Recorder(mode="record", cache=lib.CallCache(tmp_path / "c.jsonl"))


def test_snapshots_round_trip(tmp_path):
    store = lib.SnapshotStore(tmp_path / "s.json")
    store.put("k", {"query": "q", "results": [], "latency_ms": 5})
    assert lib.SnapshotStore(tmp_path / "s.json").get("k")["latency_ms"] == 5


# ------------------------------------------------------------------------------------ metrics


def test_cited_numbers_are_unique_zero_based_and_in_range():
    assert lib.cited_numbers("A [2] and B [1][2], C [9] [0]", 3) == [1, 0]
    assert lib.cited_numbers("no citations", 3) == []


def test_declined_means_no_sources_or_the_usual_refusal_words():
    assert lib.declined("anything", had_sources=False)
    assert lib.declined("The sources do not contain that.", had_sources=True)
    assert not lib.declined("Acme asked about pricing [1].", had_sources=True)


def test_recall_and_reciprocal_rank():
    assert lib.recall_at(["a", "b", "c"], {"b", "z"}, 2) == 0.5
    assert lib.reciprocal_rank(["a", "b"], {"b"}) == 0.5
    assert lib.reciprocal_rank(["a"], {"z"}) == 0.0


def test_cost_uses_the_pinned_prices():
    assert lib.cost_usd(1_000_000, 1_000_000) == pytest.approx(
        lib.PRICE_IN_PER_M + lib.PRICE_OUT_PER_M
    )


def result(id_, answerable=True, **kw) -> lib.CaseResult:
    base = dict(
        id=id_, answerable=answerable, ranked_docs=["a"], returned=2, answer="x [1]",
        declined=False, grounded=True, citations_total=1, citations_correct=1, latency_ms=100,
        tokens_in=10, tokens_out=2, llm_calls=1, extra_calls=0,
        metrics={"recall_at_1": 1.0, "recall_at_3": 1.0, "recall_at_4": 1.0, "mrr": 1.0},
    )  # fmt: skip
    base.update(kw)
    return lib.CaseResult(**base)


def test_summarise_counts_what_the_table_reports():
    rows = [
        result("a"),
        result("b", metrics={"recall_at_1": 0.0, "recall_at_3": 0.5, "recall_at_4": 0.5, "mrr": 0.5},
               citations_correct=0, grounded=False, latency_ms=300, extra_calls=3, rewritten=True),
        result("u", answerable=False, declined=True, grounded=None, returned=0,
               citations_total=0, citations_correct=0, metrics={}),
    ]  # fmt: skip

    s = lib.summarise(rows)

    assert (s["cases"], s["answerable"], s["unanswerable"]) == (3, 2, 1)
    assert s["recall_at_1"] == 0.5 and s["mrr"] == 0.75
    assert s["citation_correctness"] == 0.5
    assert s["unanswerable_declined"] == 1 and s["answerable_answered"] == 2
    assert (s["grounded"], s["answers_checked"]) == (1, 2)
    assert s["median_ms"] == 100 and s["p95_ms"] == 300
    assert s["extra_calls_per_question"] == 1.0 and s["rewritten"] == 1


def test_compare_flags_moved_numbers_and_missing_arms():
    base = {"plain": {"mrr": 0.9, "grounded": 30}, "agentic": {"mrr": 0.95}}
    same = {"plain": {"mrr": 0.9, "grounded": 30}, "agentic": {"mrr": 0.95}}
    assert lib.compare(base, same) == []
    moved = {"plain": {"mrr": 0.8, "grounded": 30}}
    problems = lib.compare(base, moved)
    assert any("plain.mrr" in p for p in problems) and any("agentic" in p for p in problems)


def test_the_table_shows_both_arms_side_by_side():
    s = lib.summarise([result("a")])
    table = lib.format_table({"plain": s, "agentic": s}, "header line")
    assert table.startswith("header line") and "plain hybrid" in table and "agentic" in table
    assert "extra calls from the layer" in table and "cost, whole run (USD)" in table


# ------------------------------------------------------------------------------------ committed files


def test_the_committed_recordings_replay_to_the_committed_baseline():
    """CI's own check: no keys, no stack, and the numbers in baseline/agentic-v1.json come out again."""
    baseline_file = EVALS / "baseline" / "agentic-v1.json"
    if not baseline_file.exists():
        pytest.skip("no agentic baseline committed yet")
    import compare_agentic

    summaries, _detail = asyncio.run(compare_agentic.run("replay"))

    assert lib.compare(json.loads(baseline_file.read_text())["arms"], summaries) == []


def test_the_call_cache_is_committed_without_any_secret_shaped_value():
    cache = EVALS / "agentic" / "cache.jsonl"
    if not cache.exists():
        pytest.skip("no recordings yet")
    for line in cache.read_text().splitlines():
        row = json.loads(line)
        assert "sk-or-v1-" not in line and "AIza" not in line
        assert set(row) >= {"sha256", "role", "model", "version", "content"}
