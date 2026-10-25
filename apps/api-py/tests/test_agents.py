import pytest

from app.agent import agents
from app.llm.types import GenerationResult


def _result(text: str) -> GenerationResult:
    return GenerationResult(content=text, provider="ollama", model="fake", tokens_in=1, tokens_out=1, latency_ms=1, estimated_cost=None)


def _fake_llm(reply: str):
    async def llm(_system, _messages):
        return _result(reply)

    return llm


def test_parse_json_handles_fences_and_prose():
    assert agents.parse_json_object('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert agents.parse_json_object("no json here") is None


def test_unreadable_review_fails_closed():
    review = agents.parse_review("looks fine to me")
    assert review.verdict == "revise"


def test_unstructured_recommendation_is_flagged_not_dropped():
    rec = agents.parse_recommendation("Call Acme about renewal.")
    assert rec.structured is False
    assert "Call Acme" in rec.action


def test_unknown_citations_detected():
    rec = agents.Recommendation(action="x", rationale="y", evidence=["E1", "E9"])
    assert agents.unknown_citations(rec, {"E1", "E2"}) == ["E9"]


def test_labels_in_evidence():
    assert agents.labels_in("E1 [CRM] a\nE2 [DOC] b\nnot a label") == {"E1", "E2"}


@pytest.mark.asyncio
async def test_analyst_includes_reviewer_feedback_on_revision():
    seen = {}

    async def llm(_system, messages):
        seen["prompt"] = messages[0]["content"]
        return _result('{"action": "Call them", "rationale": "r", "evidence": ["E1"]}')

    rec, _ = await agents.run_analyst(llm, "E1 fact", reviewer_feedback=["cite evidence"])
    assert "cite evidence" in seen["prompt"]
    assert rec.evidence == ["E1"]


@pytest.mark.asyncio
async def test_drafter_falls_back_to_action_and_caps_length():
    rec = agents.Recommendation(action="Send pricing", rationale="r")
    note, _ = await agents.run_task_drafter(_fake_llm("not json"), rec)
    assert note == "Send pricing"
    long_note, _ = await agents.run_task_drafter(_fake_llm('{"task_note": "' + "a" * 900 + '"}'), rec)
    assert len(long_note) == agents.TASK_NOTE_MAX_CHARS
