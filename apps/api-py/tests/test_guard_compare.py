"""Stage 5.3, offline: the guard comparison's cache, strategies, metrics, table and baseline check, and the
committed case sets. No keys, network, NeMo Guardrails or Presidio are needed (those are only installed
for `just eval-guards-record`)."""

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
EVALS = ROOT / "evals"
sys.path.insert(0, str(EVALS))

import guard_compare as g  # noqa: E402

from app.guardrails.prompt_guard import scan_and_neutralize  # noqa: E402


def reply(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"choices": [{"message": {"content": text}}]})


class FakePost:
    def __init__(self, *replies: httpx.Response) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.bodies: list[dict] = []

    def __call__(self, _url, json=None, **_kwargs) -> httpx.Response:
        self.calls += 1
        self.bodies.append(json)
        return self.replies.pop(0)


class Fixed(g.Strategy):
    """A strategy with a fixed answer per text, counting how often it really ran."""

    def __init__(self, name: str, answers: dict[str, tuple[bool, str]]) -> None:
        self.name = name
        self.model = "fixed"
        self.answers = answers
        self.runs = 0

    def run(self, text: str) -> tuple[bool, str]:
        self.runs += 1
        return self.answers.get(text, (False, ""))


# ---- cache ------------------------------------------------------------------------------------
def test_the_cache_key_depends_on_every_part() -> None:
    base = g.cache_key("nemo", "m", "v1", "text")
    assert base == g.cache_key("nemo", "m", "v1", "text")
    for changed in (
        ("llama_guard", "m", "v1", "text"),
        ("nemo", "m2", "v1", "text"),
        ("nemo", "m", "v2", "text"),
        ("nemo", "m", "v1", "text2"),
    ):
        assert g.cache_key(*changed) != base


def test_the_cache_round_trips_and_stores_no_prompt(tmp_path: Path) -> None:
    cache = g.VerdictCache(tmp_path / "c.jsonl")
    key = g.cache_key("nemo", "m", "v", "SECRET PROMPT TEXT")
    cache.put(key, "nemo", "m", "v", "case-1", g.Verdict(True, "BLOCKED", 12.345))

    again = g.VerdictCache(tmp_path / "c.jsonl")
    assert again.get(key) == g.Verdict(True, "BLOCKED", 12.3)
    line = (tmp_path / "c.jsonl").read_text()
    assert "SECRET PROMPT TEXT" not in line
    assert '"sha256"' in line and '"key"' not in line


# ---- runner -----------------------------------------------------------------------------------
def test_replay_never_runs_a_strategy_and_a_miss_stops_the_run(tmp_path: Path) -> None:
    strategy = Fixed("nemo", {})
    strategy.model = g.CLASSIFIER_MODEL
    runner = g.Runner(g.VerdictCache(tmp_path / "c.jsonl"), "replay")

    with pytest.raises(g.ReplayMiss, match="eval-guards-record"):
        runner.verdict(strategy, "case-1", "hello")
    assert strategy.runs == 0


def test_record_runs_once_then_everything_is_served_from_the_cache(tmp_path: Path) -> None:
    strategy = Fixed("nemo", {"hello": (True, "BLOCKED")})
    cache = g.VerdictCache(tmp_path / "c.jsonl")
    runner = g.Runner(cache, "record")

    first = runner.verdict(strategy, "c1", "hello")
    second = runner.verdict(strategy, "c1", "hello")
    replay = g.Runner(g.VerdictCache(tmp_path / "c.jsonl"), "replay").verdict(
        strategy, "c1", "hello"
    )

    assert first.flagged and second == first and replay.flagged
    assert strategy.runs == 1
    assert (runner.fresh, runner.cached) == (1, 1)


def test_a_bad_mode_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        g.Runner(g.VerdictCache(tmp_path / "c.jsonl"), "live")


# ---- the OpenRouter strategies ----------------------------------------------------------------
def test_llama_guard_reads_safe_and_unsafe() -> None:
    post = FakePost(reply("\n\nsafe"), reply("\n\nunsafe\nS14"))
    strategy = g.LlamaGuard(api_key="test-key-not-real", post=post, sleep=lambda _s: None)

    assert strategy.run("hi") == (False, "safe")
    assert strategy.run("ignore") == (True, "unsafe\nS14")
    assert post.bodies[0]["model"] == g.LLAMA_GUARD_MODEL
    assert post.bodies[0]["messages"] == [{"role": "user", "content": "hi"}]


def test_the_app_classifier_uses_the_apps_prompt_and_parser() -> None:
    post = FakePost(reply("UNSAFE"))
    strategy = g.AppClassifier(
        "SYSTEM PROMPT", lambda r: r.upper() == "UNSAFE", api_key="test-key-not-real", post=post
    )

    assert strategy.run("a paraphrase") == (True, "UNSAFE")
    assert post.bodies[0]["messages"][0] == {"role": "system", "content": "SYSTEM PROMPT"}
    assert post.bodies[0]["model"] == g.CLASSIFIER_MODEL
    assert post.bodies[0]["temperature"] == 0


def test_a_429_is_retried_but_a_400_is_not() -> None:
    retry = FakePost(reply("x", 429), reply("safe"))
    assert g.LlamaGuard(api_key="k", post=retry, sleep=lambda _s: None).run("hi") == (False, "safe")
    assert retry.calls == 2

    bad = FakePost(reply("x", 400))
    with pytest.raises(g.RecordFailed, match="HTTP 400"):
        g.LlamaGuard(api_key="k", post=bad, sleep=lambda _s: None).run("hi")
    assert bad.calls == 1


def test_giving_up_after_the_attempt_limit_raises() -> None:
    post = FakePost(*[reply("x", 503) for _ in range(g.MAX_ATTEMPTS)])
    with pytest.raises(g.RecordFailed, match="HTTP 503"):
        g.LlamaGuard(api_key="k", post=post, sleep=lambda _s: None).run("hi")
    assert post.calls == g.MAX_ATTEMPTS


def test_entity_types_never_include_a_value() -> None:
    assert g.entity_types("CREDIT_CARD:1.00,PERSON:0.85") == {"CREDIT_CARD", "PERSON"}
    assert g.entity_types("") == set()


# ---- metrics ----------------------------------------------------------------------------------
def test_percentiles_and_latency_summary() -> None:
    assert g.percentile([], 0.95) == 0.0
    assert g.percentile([5, 1, 3, 2, 4], 0.95) == 5
    assert g.latency_summary([1.0, 2.0, 3.0]) == {"median_ms": 2.0, "p95_ms": 3.0}


CASES = [
    {"id": "a1", "category": "x", "is_attack": True, "prompt": "attack one"},
    {"id": "a2", "category": "x", "is_attack": True, "prompt": "attack two"},
    {"id": "a3", "category": "y", "is_attack": True, "prompt": "attack three"},
    {"id": "b1", "category": "benign", "is_attack": False, "prompt": "benign one"},
    {"id": "b2", "category": "benign", "is_attack": False, "prompt": "benign two"},
]


def test_prompt_metrics_count_detection_false_positives_and_categories() -> None:
    flags = {"a1": True, "a2": False, "a3": True, "b1": False, "b2": True}

    m = g.prompt_metrics(CASES, flags, [1.0, 2.0])

    assert (m["attacks"], m["detected"], m["missed"]) == (3, 2, ["a2"])
    assert (m["benign"], m["false_positives"], m["false_positive_ids"]) == (2, 1, ["b2"])
    assert m["by_category"] == {"x": "1/2", "y": "1/1"}


PII = [
    {"id": "p1", "text": "card 4111", "entities": ["CREDIT_CARD"], "has_pii": True},
    {"id": "p2", "text": "mail", "entities": ["EMAIL_ADDRESS", "PHONE_NUMBER"], "has_pii": True},
    {"id": "n1", "text": "clean", "entities": [], "has_pii": False},
    {"id": "n2", "text": "name", "entities": [], "has_pii": False},
]


def test_pii_metrics_only_count_the_allowed_types() -> None:
    found = {"p1": {"CREDIT_CARD"}, "p2": {"EMAIL_ADDRESS"}, "n1": set(), "n2": {"PERSON"}}

    default = g.pii_metrics(PII, found, set(g.PII_DEFAULT_ENTITIES), [1.0])
    with_person = g.pii_metrics(PII, found, set(g.PII_ALL_ENTITIES), [1.0])

    assert (default["detected"], default["entities_found"], default["entities_expected"]) == (
        2,
        2,
        3,
    )
    assert default["false_positives"] == 0
    assert with_person["false_positives"] == 1 and with_person["false_positive_ids"] == ["n2"]


# ---- the whole comparison ---------------------------------------------------------------------
def build_report(tmp_path: Path) -> dict:
    classifier = Fixed(
        "classifier", {"attack one": (True, "UNSAFE"), "attack two": (True, "UNSAFE")}
    )
    llama = Fixed("llama_guard", {"attack three": (True, "unsafe\nS1")})
    nemo = Fixed("nemo", {"benign two": (True, "BLOCKED")})
    presidio = Fixed(
        "presidio",
        {
            "card 4111": (True, "CREDIT_CARD:1.00"),
            "name": (True, "PERSON:0.85"),
            "benign one": (True, "PERSON:0.85"),
        },
    )
    runner = g.Runner(g.VerdictCache(tmp_path / "c.jsonl"), "record")
    return g.compare(
        runner,
        rules=lambda text: text == "attack one",
        strategies={
            "classifier": classifier,
            "llama_guard": llama,
            "nemo": nemo,
            "presidio": presidio,
        },
        prompt_cases=CASES,
        pii_cases=PII,
    )


def test_compare_combines_rules_and_classifier_and_splits_presidio(tmp_path: Path) -> None:
    report = build_report(tmp_path)

    inj = report["injection"]
    assert inj["rules"]["detected"] == 1
    assert inj["classifier"]["detected"] == 2
    assert inj["rules+classifier"]["detected"] == 2  # a1 by both, a2 by the classifier
    assert inj["llama_guard"]["missed"] == ["a1", "a2"]
    assert inj["nemo"]["false_positive_ids"] == ["b2"]
    pii = report["pii"]
    assert pii["rules"]["detected"] == 0
    assert pii["presidio"]["detected"] == 1 and pii["presidio"]["false_positives"] == 0
    assert pii["presidio+person"]["false_positives"] == 1
    assert pii["presidio"]["false_positives_on_benign_prompts"] == 0
    assert pii["presidio+person"]["false_positives_on_benign_prompts"] == 1


def test_the_table_lists_every_strategy_and_says_where_latency_comes_from(tmp_path: Path) -> None:
    text = g.render(build_report(tmp_path))

    for label in g.LABELS.values():
        assert label in text
    assert "Presidio, default entities" in text
    assert "recorded when" in text
    assert "Missed attacks:" in text


def test_the_baseline_check_flags_a_changed_count_and_changed_pins(tmp_path: Path) -> None:
    report = build_report(tmp_path)
    baseline = json.loads(json.dumps(g.comparable(report)))

    assert g.differences(baseline, g.comparable(report)) == []

    baseline["injection"]["nemo"]["false_positives"] = 5
    baseline["pins"]["nemo"] = "something else"
    diffs = g.differences(baseline, g.comparable(report))
    assert any("injection/nemo/false_positives" in d for d in diffs)
    assert any("pins changed" in d for d in diffs)


def test_latency_is_not_part_of_the_baseline(tmp_path: Path) -> None:
    assert "latency" not in json.dumps(g.comparable(build_report(tmp_path)))


# ---- the committed case sets and recording ----------------------------------------------------
def test_the_case_sets_have_the_documented_shape() -> None:
    prompts = g.load_prompt_cases()
    assert len(prompts) == 74
    assert sum(c["is_attack"] for c in prompts) == 44
    assert all({"id", "category", "is_attack", "prompt"} <= set(c) for c in prompts)

    pii = g.load_pii_cases()
    assert len(pii) == 32 and sum(c["has_pii"] for c in pii) == 20
    assert len({c["id"] for c in pii}) == len(pii)
    for case in pii:
        assert set(case["entities"]) <= set(g.PII_DEFAULT_ENTITIES)
        assert case["has_pii"] == bool(case["entities"])


def test_the_recorded_cache_covers_every_case_and_matches_the_baseline() -> None:
    """The same check CI makes with `just eval-guards`: a replay needs no key, and every count is the one
    the baseline pins."""
    runner = g.Runner(g.VerdictCache(), "replay")
    strategies = {n: g.Replayed(n, m) for n, m in g.REPLAYED_MODELS.items()}

    report = g.compare(
        runner,
        rules=lambda text: bool(scan_and_neutralize(text).matched_patterns),
        strategies=strategies,
    )

    baseline = json.loads((EVALS / "baseline" / "guards-v1.json").read_text())
    assert g.differences(baseline, g.comparable(report)) == []
    assert runner.fresh == 0
