import pytest

from app.agent.policies import AgentLimits, BudgetExceeded, RunBudget, needs_agent
from app.agent.trace import SUMMARY_MAX_CHARS, Trace


def test_budget_stops_after_max_steps():
    budget = RunBudget(AgentLimits(max_steps=2))
    budget.spend()
    budget.spend()
    with pytest.raises(BudgetExceeded):
        budget.spend()


def test_budget_stops_after_timeout():
    budget = RunBudget(AgentLimits(timeout_seconds=-1))
    with pytest.raises(BudgetExceeded):
        budget.spend()


def test_limits_come_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_STEPS", "3")
    monkeypatch.setenv("AGENT_MAX_REVISIONS", "0")
    limits = AgentLimits.from_env()
    assert limits.max_steps == 3
    assert limits.max_revisions == 0


@pytest.mark.parametrize(
    "message",
    ["Analyze Acme Fabrication's account and recommend a next action", "What should we do about Northstar?"],
)
def test_analysis_requests_use_agent(message):
    assert needs_agent(message)


@pytest.mark.parametrize("message", ["What is Acme's industry?", "List the open deals for Harbor & Pine"])
def test_simple_questions_bypass_agent(message):
    assert not needs_agent(message)


def test_trace_records_ordered_shortened_steps():
    import time

    trace = Trace()
    trace.record("tool", "get_company_summary", "Acme", "x" * 1000, time.monotonic())
    trace.record("agent", "analyst", "evidence", "recommendation", time.monotonic(), status="ok")
    steps = trace.to_list()
    assert [s["index"] for s in steps] == [1, 2]
    assert len(steps[0]["output_summary"]) <= SUMMARY_MAX_CHARS
    assert steps[1]["kind"] == "agent"
