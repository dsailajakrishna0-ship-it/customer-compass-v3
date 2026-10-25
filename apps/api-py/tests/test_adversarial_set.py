"""Stage 8.a: runs the shared adversarial fixture (evals/adversarial-prompts.json)
through the rule-based guard, no LLM needed. `rules_catch` records what the
regex rules are expected to do, so known gaps (paraphrase, leetspeak) are
explicit and any regression or improvement shows up as a test change."""

import json
from pathlib import Path

import pytest

from app.guardrails.prompt_guard import scan_and_neutralize

FIXTURE = Path(__file__).resolve().parents[3] / "evals" / "adversarial-prompts.json"
CASES = json.loads(FIXTURE.read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_rules_match_expected_detection(case: dict) -> None:
    finding = scan_and_neutralize(case["prompt"])
    assert finding.flagged is case["rules_catch"]


def test_no_benign_prompt_is_flagged() -> None:
    assert not [c["id"] for c in CASES if not c["is_attack"] and scan_and_neutralize(c["prompt"]).flagged]


def test_rules_never_claim_to_catch_a_benign_prompt() -> None:
    assert all(not (c["rules_catch"] and not c["is_attack"]) for c in CASES)
