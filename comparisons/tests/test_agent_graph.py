"""Both agent approaches against a scripted model: the same run (look the company up, recommend one
action, pause, resume), written two ways. No key, no network. See docs/adr/0041."""

import json

import pytest
from agent_graph_with_langchain import LangChainAgent
from agent_graph_with_langgraph import LangGraphAgent
from lab_common.agent import (
    BoundedRuns,
    CompanyNotFoundError,
    NotAwaitingApprovalError,
    UnknownRunError,
)
from lab_common.chat import UnavailableError
from lab_common.recommender import Recommender, parse_recommendation
from lab_common.testing import ai, scripted, tool_call
from langchain_core.messages import ToolMessage

ACTION = "Call Maya about the renewal."
RATIONALE = "The renewal deal is open."


def langgraph(crm_tools, action=ACTION, rationale=RATIONALE, reply=None):
    model = scripted(
        ai(reply if reply is not None else json.dumps({"action": action, "rationale": rationale}))
    )
    return LangGraphAgent(crm_tools, Recommender(model=model)), model


def langchain(crm_tools, company="Acme", action=ACTION, rationale=RATIONALE, extra=()):
    model = scripted(
        ai("", [tool_call("get_company_summary", {"company_name": company}, "c1")]),
        ai(
            "",
            [
                tool_call(
                    "create_followup_task",
                    {"company_name": "Acme Fabrication", "action": action, "rationale": rationale},
                    "c2",
                )
            ],
        ),
        ai("Task created."),
        *extra,
    )
    return LangChainAgent(crm_tools, model=model), model


BUILDERS = [langgraph, langchain]


@pytest.mark.parametrize("build", BUILDERS)
def test_start_runs_to_the_pause_and_shows_the_recommendation(build, crm_tools):
    agent, _ = build(crm_tools)
    outcome = agent.start("Acme", None)
    assert outcome.status == "awaiting_approval"
    assert [(s.name, s.status) for s in outcome.steps] == [
        ("gather", "done"),
        ("recommend", "done"),
        ("approval", "waiting"),
        ("act", "pending"),
    ]
    assert (outcome.recommendation.action, outcome.recommendation.rationale) == (ACTION, RATIONALE)
    assert outcome.message == "Waiting for approval of the recommended action."


@pytest.mark.parametrize("build", BUILDERS)
def test_approving_completes_the_run_as_a_dry_run(build, crm_tools):
    agent, _ = build(crm_tools)
    run = agent.start("Acme", None).run_id
    outcome = agent.resume(run, True)
    assert outcome.status == "completed" and [s.status for s in outcome.steps] == ["done"] * 4
    assert (
        outcome.message
        == f"Approved. Dry run: this would create a follow-up task for Acme Fabrication: {ACTION} Nothing was written."
    )


@pytest.mark.parametrize("build", BUILDERS)
def test_declining_ends_the_run_and_does_nothing(build, crm_tools):
    agent, _ = build(crm_tools)
    run = agent.start("Acme", None).run_id
    outcome = agent.resume(run, False)
    assert outcome.status == "declined" and [s.status for s in outcome.steps] == [
        "done",
        "done",
        "declined",
        "skipped",
    ]
    assert outcome.message == "Declined. Nothing was done."


@pytest.mark.parametrize("build", BUILDERS)
def test_a_run_can_be_answered_once(build, crm_tools):
    agent, _ = build(crm_tools)
    run = agent.start("Acme", None).run_id
    agent.resume(run, True)
    with pytest.raises(NotAwaitingApprovalError, match="already completed"):
        agent.resume(run, True)


@pytest.mark.parametrize("build", BUILDERS)
def test_an_unknown_run_id_is_unknown(build, crm_tools):
    agent, _ = build(crm_tools)
    with pytest.raises(UnknownRunError):
        agent.resume("0b8f7c2e-6a51-4c0e-9d57-7f1f0b3c1a11", True)


def test_an_unknown_company_is_not_found_in_both(crm_tools):
    graph, _ = langgraph(crm_tools)
    chain = LangChainAgent(
        crm_tools,
        model=scripted(
            ai("", [tool_call("get_company_summary", {"company_name": "Nobody"}, "c1")]),
            ai("No such company."),
        ),
    )
    for agent in (graph, chain):
        with pytest.raises(CompanyNotFoundError, match="Nobody"):
            agent.start("Nobody", None)


@pytest.mark.parametrize("build", BUILDERS)
def test_a_recommendation_that_is_unusable_is_refused(build, crm_tools):
    agent, _ = build(crm_tools, action="x" * 201)
    with pytest.raises(UnavailableError, match="usable recommendation"):
        agent.start("Acme", None)


@pytest.mark.parametrize("build", BUILDERS)
def test_no_key_means_no_call(build, crm_tools):
    agent = (
        LangGraphAgent(crm_tools, Recommender())
        if build is langgraph
        else LangChainAgent(crm_tools)
    )
    with pytest.raises(UnavailableError, match="OPENROUTER_API_KEY"):
        agent.start("Acme", None)


def test_a_failing_model_call_is_reported_by_kind_never_by_the_services_text(crm_tools):
    graph = LangGraphAgent(
        crm_tools, Recommender(model=scripted())
    )  # an empty script: the model raises
    chain = LangChainAgent(crm_tools, model=scripted())
    for agent in (graph, chain):
        with pytest.raises(UnavailableError) as info:
            agent.start("Acme", None)
        assert "more often than the test scripted" not in str(
            info.value
        ) and "AssertionError" in str(info.value)


def test_only_the_most_recent_runs_are_kept_and_an_evicted_run_loses_its_saved_state(crm_tools):
    agent, _ = langgraph(crm_tools)
    agent._runs = BoundedRuns(capacity=1, on_evict=agent._saver.delete_thread)
    first = agent.start("Acme", None).run_id
    agent._recommender = Recommender(
        model=scripted(ai(json.dumps({"action": ACTION, "rationale": RATIONALE})))
    )
    second = agent.start("Acme", None).run_id
    with pytest.raises(UnknownRunError):
        agent.resume(first, True)
    assert agent._saver.get_tuple({"configurable": {"thread_id": first}}) is None
    assert agent._saver.get_tuple({"configurable": {"thread_id": second}}) is not None


def test_the_recommendation_parser_accepts_a_code_fence_and_refuses_the_rest():
    fenced = '```json\n{"action": "Call.", "rationale": "Because."}\n```'
    assert parse_recommendation(fenced).action == "Call."
    for bad in (
        "",
        "not json",
        "[1]",
        '{"action": ""}',
        '{"action": "a", "rationale": "' + "r" * 401 + '"}',
    ):
        with pytest.raises(UnavailableError):
            parse_recommendation(bad)


# What each framework did on its own (measured).


def test_measured_langgraph_calls_the_model_once_and_does_not_repeat_it_on_resume(crm_tools):
    agent, model = langgraph(crm_tools)
    run = agent.start("Acme", None).run_id
    agent.resume(run, True)
    assert len(model.seen) == 1  # code decides the steps: gather and act need no model


def test_measured_langchain_calls_the_model_three_times_for_the_same_run(crm_tools):
    agent, model = langchain(crm_tools)
    run = agent.start("Acme", None).run_id
    assert len(model.seen) == 2  # look up, then recommend (the paused call)
    agent.resume(run, True)
    assert len(model.seen) == 3  # and a last message after the tool ran


def test_measured_langchain_runs_the_gated_tool_only_after_the_approval(crm_tools):
    agent, model = langchain(crm_tools)
    run = agent.start("Acme", None).run_id

    def ran():
        return [
            m
            for call in model.seen
            for m in call
            if isinstance(m, ToolMessage) and m.name == "create_followup_task"
        ]

    assert ran() == []
    agent.resume(run, True)
    assert len(ran()) == 1


def test_measured_langchain_needs_the_model_to_call_the_tools_or_the_run_never_pauses(crm_tools):
    agent = LangChainAgent(crm_tools, model=scripted(ai("I think you should call Maya.")))
    with pytest.raises(UnavailableError, match="did not reach the approval step"):
        agent.start("Acme", None)


def test_measured_the_frameworks_own_reject_hands_the_rejection_to_the_model_and_the_loop_goes_on(
    crm_tools,
):
    from langgraph.types import Command

    agent, model = langchain(crm_tools, extra=(ai("Understood, nothing was created."),))
    run = agent.start("Acme", None)
    stored = agent._runs.get(run.run_id)
    config = {"configurable": {"thread_id": run.run_id}}
    stored.agent.invoke(
        Command(resume={"decisions": [{"type": "reject", "message": "No."}]}), config
    )
    assert len(model.seen) == 3  # one more model call, which a decline through our own code avoids
    names = [m.name for call in model.seen for m in call if isinstance(m, ToolMessage)]
    assert names.count("create_followup_task") == 1 and "Dry run" not in str(
        [m.content for call in model.seen for m in call if isinstance(m, ToolMessage)]
    )


def test_measured_the_langgraph_approval_node_runs_again_from_its_first_line_on_resume(crm_tools):
    import agent_graph_with_langgraph as module

    agent, _ = langgraph(crm_tools)
    entered = []
    real = module.interrupt
    module.interrupt = lambda value: entered.append(1) or real(value)
    try:
        run = agent.start("Acme", None).run_id
        agent.resume(run, True)
    finally:
        module.interrupt = real
    assert len(entered) == 2  # once to pause, once more to return the answer


def test_measured_the_checkpointer_keeps_a_finished_run_until_it_is_deleted(crm_tools):
    agent, _ = langgraph(crm_tools)
    run = agent.start("Acme", None).run_id
    agent.resume(run, True)
    assert agent._saver.get_tuple({"configurable": {"thread_id": run}}) is not None
