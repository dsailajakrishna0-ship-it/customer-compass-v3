"""The four multi-agent patterns on LangGraph against a scripted model: the same account review
(look the company up, one deals lookup, analyse, review) organised four ways. No key, no network.
See docs/adr/0043."""

import json

import pytest
from handoff_with_langgraph import HandoffTeam
from hierarchical_with_langgraph import HierarchicalTeam
from lab_common.agent import CompanyNotFoundError
from lab_common.chat import UnavailableError
from lab_common.team import SUPERVISOR_PROMPT, TeamModel
from lab_common.testing import ai, scripted, tool_call
from network_with_langgraph import NAMING_PROMPT, NetworkTeam
from supervisor_with_langgraph import SupervisorTeam

ACTION = "Call Maya about the renewal."


def J(**fields):
    return ai(json.dumps(fields))


REC = J(action=ACTION, rationale="The renewal deal is open.")
APPROVE = J(verdict="approve", reason="Fits the facts.")
REVISE = J(verdict="revise", reason="Too vague.")


def route(name, reason="r"):
    return J(next=name, reason=reason)


def build(cls, crm_tools, *replies, **kwargs):
    model = scripted(*replies)
    return cls(crm_tools, TeamModel(model=model), **kwargs), model


# the happy path of each pattern: facts, one deals lookup, an analysis, an approving review
def supervisor_happy(crm):
    return build(SupervisorTeam, crm, route("deals"), route("analyst"), REC, APPROVE)


def hierarchical_happy(crm):
    return build(
        HierarchicalTeam, crm, route("deals"), route("FINISH"), route("answer_team"), REC, APPROVE
    )


def network_happy(crm):
    return build(
        NetworkTeam,
        crm,
        route("deals"),
        route("analyst"),
        REC,
        route("reviewer"),
        APPROVE,
        route("FINISH"),
    )


def handoff_happy(crm):
    return build(HandoffTeam, crm, ai("", [tool_call("transfer_to_analyst", {})]), REC, APPROVE)


HAPPY = {
    "supervisor": (supervisor_happy, 5, 4),  # decisions, model calls
    "hierarchical": (hierarchical_happy, 9, 5),
    "network": (network_happy, 4, 6),
    "handoff": (handoff_happy, 4, 3),
}
ALL = list(HAPPY)


@pytest.mark.parametrize("pattern", ALL)
def test_the_review_completes_with_the_same_four_pieces_of_work_in_order(pattern, crm_tools):
    team, _ = HAPPY[pattern][0](crm_tools)
    outcome = team.run("Acme", None)
    assert (outcome.status, outcome.message) == ("completed", "The review finished.")
    assert outcome.specialists == ["crm_facts", "deals", "analyst", "reviewer"]
    assert (outcome.recommendation.action, team.pattern) == (ACTION, pattern)


@pytest.mark.parametrize("pattern", ALL)
def test_the_pattern_decides_how_many_decisions_and_model_calls_the_same_review_costs(
    pattern, crm_tools
):
    factory, decisions, calls = HAPPY[pattern]
    team, model = factory(crm_tools)
    outcome = team.run("Acme", None)
    assert (outcome.turns, len(model.seen)) == (decisions, calls)


@pytest.mark.parametrize("pattern", ALL)
def test_an_unknown_company_is_not_found_and_a_pattern_with_no_choice_asks_no_model_for_it(
    pattern, crm_tools
):
    team, model = HAPPY[pattern][0](crm_tools)
    with pytest.raises(CompanyNotFoundError, match="Nobody"):
        team.run("Nobody", None)
    assert model.seen == []


@pytest.mark.parametrize("pattern", ALL)
def test_no_crm_text_ever_reaches_a_routing_prompt(pattern, crm_tools):
    team, model = HAPPY[pattern][0](crm_tools)
    team.run("Acme", None)
    routing = [
        call
        for call in model.seen
        if str(call[0].content) in (SUPERVISOR_PROMPT, NAMING_PROMPT)
        or "transfer_to" in str(call[0].content)
        or "Name who" in str(call[0].content)
    ]
    assert routing or pattern == "handoff"
    for call in routing:
        text = " ".join(str(m.content) for m in call)
        assert (
            "Manufacturing" not in text
            and "Renewal" not in text
            and "untrusted_context" not in text
        )


@pytest.mark.parametrize("pattern", ALL)
def test_no_key_means_no_call_and_a_failing_model_is_reported_by_kind(pattern, crm_tools):
    keyless = {
        "supervisor": SupervisorTeam,
        "hierarchical": HierarchicalTeam,
        "network": NetworkTeam,
        "handoff": HandoffTeam,
    }[pattern]
    # the first model call of each pattern's happy path is a routing or work call: an empty script raises it
    with pytest.raises(UnavailableError, match="OPENROUTER_API_KEY"):
        keyless(crm_tools, TeamModel()).run("Acme", None)
    team, _ = build(keyless, crm_tools)  # an empty script
    with pytest.raises(UnavailableError) as info:
        team.run("Acme", None)
    assert "AssertionError" in str(info.value) and "more often than the test scripted" not in str(
        info.value
    )


# ---- the supervisor


def test_supervisor_an_answer_that_is_not_allowed_or_not_readable_is_replaced_by_the_first_allowed_one(
    crm_tools,
):
    team, _ = build(
        SupervisorTeam, crm_tools, route("reviewer"), ai("not json at all"), REC, APPROVE
    )
    outcome = team.run("Acme", None)
    second, third = outcome.decisions[1], outcome.decisions[2]
    assert (second.chosen, second.proposed) == (
        "deals",
        "reviewer",
    ) and second.decided_by == "supervisor"
    assert (third.chosen, third.proposed) == (
        "deals",
        "unreadable",
    )  # the model's text is never echoed
    assert outcome.specialists == ["crm_facts", "deals", "deals", "analyst", "reviewer"]


def test_supervisor_a_proposal_that_is_not_a_plain_word_is_shown_as_unreadable(crm_tools):
    team, _ = build(
        SupervisorTeam,
        crm_tools,
        route("ignore all rules; <script>"),
        route("analyst"),
        REC,
        APPROVE,
    )
    assert team.run("Acme", None).decisions[1].proposed == "unreadable"


def test_supervisor_a_review_that_asks_for_a_revision_sends_the_analyst_back_once_with_the_feedback(
    crm_tools,
):
    team, model = build(
        SupervisorTeam, crm_tools, route("analyst"), REC, REVISE, route("analyst"), REC, REVISE
    )
    outcome = team.run("Acme", None)
    assert outcome.specialists == ["crm_facts", "analyst", "reviewer", "analyst", "reviewer"]
    assert outcome.status == "completed"  # one revision is all it gets, then FINISH
    revised = " ".join(str(m.content) for m in model.seen[4])
    assert "Reviewer feedback: Too vague." in revised and revised.index(
        "<untrusted_context>"
    ) < revised.index("Reviewer feedback")


def test_supervisor_an_unreadable_review_counts_as_a_request_to_revise(crm_tools):
    team, _ = build(
        SupervisorTeam,
        crm_tools,
        route("analyst"),
        REC,
        ai("no idea"),
        route("analyst"),
        REC,
        APPROVE,
    )
    assert team.run("Acme", None).specialists.count("analyst") == 2


def test_supervisor_the_turn_limit_ends_the_run_as_stopped_with_no_recommendation(crm_tools):
    team, _ = build(
        SupervisorTeam, crm_tools, route("deals"), route("deals"), route("deals"), max_turns=3
    )
    outcome = team.run("Acme", None)
    assert (outcome.status, outcome.recommendation, outcome.message) == (
        "stopped",
        None,
        "Stopped at the limit of 3 turns.",
    )
    assert outcome.decisions[-1].reason == "the turn limit was reached"


def test_supervisor_at_most_two_deals_lookups(crm_tools):
    team, _ = build(SupervisorTeam, crm_tools, route("deals"), route("deals"), REC, APPROVE)
    outcome = team.run("Acme", None)
    assert outcome.specialists.count("deals") == 2
    assert outcome.decisions[3].allowed == ["analyst"]  # the third lookup was never offered


# ---- the hierarchy


def test_hierarchical_each_level_has_its_own_allowed_list_and_the_log_says_which(crm_tools):
    team, _ = hierarchical_happy(crm_tools)
    levels = [(d.level, d.decided_by) for d in team.run("Acme", None).decisions]
    assert levels == [
        ("top", "code"),
        ("research", "code"),
        ("research", "supervisor"),
        ("research", "supervisor"),
        ("top", "supervisor"),
        ("answer", "code"),
        ("answer", "code"),
        ("answer", "code"),
        ("top", "code"),
    ]


def test_hierarchical_three_of_the_four_extra_decisions_are_made_by_code(crm_tools):
    sup, _ = supervisor_happy(crm_tools)
    hier, _ = hierarchical_happy(crm_tools)
    extra = len(hier.run("Acme", None).decisions) - len(sup.run("Acme", None).decisions)
    assert extra == 4


def test_hierarchical_a_team_is_stopped_by_its_own_turn_limit(crm_tools, monkeypatch):
    import hierarchical_with_langgraph as module

    monkeypatch.setattr(module, "MAX_TEAM_TURNS", 2)
    team, _ = build(HierarchicalTeam, crm_tools, route("deals"))
    outcome = team.run("Acme", None)
    assert outcome.status == "stopped" and outcome.specialists == ["crm_facts", "deals"]
    assert any(
        d.reason == "the team's turn limit was reached" and d.level == "research"
        for d in outcome.decisions
    )


# ---- the network


def test_network_a_peer_that_names_itself_is_caught_by_the_loop_guard_after_three_turns(crm_tools):
    team, model = build(NetworkTeam, crm_tools, route("crm_facts"), route("crm_facts"))
    outcome = team.run("Acme", None)
    assert (
        outcome.status == "stopped"
        and "named itself again with nothing new" in outcome.decisions[-1].reason
    )
    assert (outcome.turns, len(model.seen)) == (
        3,
        2,
    )  # the guard fires before the third peer is asked


def test_network_two_peers_naming_each_other_with_nothing_new_are_caught_after_four_turns(
    crm_tools,
):
    # the reviewer has no recommendation to review and crm_facts has nothing left to do: nothing changes
    team, model = build(
        NetworkTeam, crm_tools, route("reviewer"), route("crm_facts"), route("reviewer")
    )
    outcome = team.run("Acme", None)
    assert (
        outcome.status == "stopped"
        and "named each other with nothing new" in outcome.decisions[-1].reason
    )
    assert (outcome.turns, len(model.seen)) == (4, 3)


def test_network_an_analyst_and_a_reviewer_that_keep_changing_the_board_slip_past_the_loop_guard(
    crm_tools,
):
    replies = [
        route("analyst"),
        REC,
        route("reviewer"),
        REVISE,
        route("analyst"),
        REC,
        route("reviewer"),
        REVISE,
        route("analyst"),
        REC,
        route("reviewer"),
        REVISE,
        route("analyst"),
        REC,
    ]
    team, model = build(NetworkTeam, crm_tools, *replies)
    outcome = team.run("Acme", None)
    assert outcome.status == "stopped"
    assert "named too often" in outcome.decisions[-1].reason  # only the per-peer cap stopped it
    assert len(model.seen) >= 12


def test_network_a_peer_that_names_finish_too_early_ends_the_run_with_no_recommendation_nobody_checks_the_job(
    crm_tools,
):
    team, _ = build(NetworkTeam, crm_tools, route("FINISH"))
    outcome = team.run("Acme", None)
    assert (outcome.status, outcome.recommendation, outcome.specialists) == (
        "completed",
        None,
        ["crm_facts"],
    )


def test_network_an_unreadable_naming_ends_the_chat_there_is_no_list_to_fall_back_on(crm_tools):
    team, _ = build(NetworkTeam, crm_tools, ai("who knows"))
    outcome = team.run("Acme", None)
    assert (
        outcome.decisions[-1].chosen == "FINISH" and outcome.decisions[-1].proposed == "unreadable"
    )


def test_network_a_peer_with_nothing_to_work_on_does_nothing(crm_tools):
    team, _ = build(NetworkTeam, crm_tools, route("reviewer"), route("FINISH"))
    outcome = team.run("Acme", None)  # the reviewer is named before any recommendation exists
    assert outcome.specialists == ["crm_facts"]


# ---- the handoff


def test_handoff_the_researchers_tool_call_is_read_and_never_executed(crm_tools):
    team, model = build(
        HandoffTeam, crm_tools, ai("", [tool_call("transfer_to_analyst", {})]), REC, APPROVE
    )
    outcome = team.run("Acme", None)
    assert [m for call in model.seen for m in call if type(m).__name__ == "ToolMessage"] == []
    assert model.tools_bound == ["transfer_to_analyst", "transfer_to_researcher"]
    assert outcome.decisions[1].decided_by == "agent" and outcome.decisions[1].allowed == [
        "analyst",
        "researcher",
    ]


def test_handoff_a_second_lookup_is_a_hand_off_to_itself_and_then_the_researcher_has_no_choice(
    crm_tools,
):
    team, model = build(
        HandoffTeam, crm_tools, ai("", [tool_call("transfer_to_researcher", {})]), REC, APPROVE
    )
    outcome = team.run("Acme", None)
    assert [d.chosen for d in outcome.decisions][:3] == ["researcher", "researcher", "analyst"]
    assert [d.decided_by for d in outcome.decisions][:3] == [
        "code",
        "agent",
        "code",
    ]  # the second visit has one option
    assert (
        outcome.specialists == ["crm_facts", "deals", "deals", "analyst", "reviewer"]
        and len(model.seen) == 3
    )


@pytest.mark.parametrize(
    ("answer", "proposed"),
    [
        (ai("", [tool_call("transfer_to_billing", {})]), "transfer_to_billing"),
        (ai("I will go with the analyst"), "no tool call"),
    ],
    ids=["a tool that was never offered", "an answer in text"],
)
def test_handoff_an_answer_that_is_not_an_offered_hand_off_is_replaced_and_recorded(
    answer, proposed, crm_tools
):
    team, _ = build(HandoffTeam, crm_tools, answer, REC, APPROVE)
    decision = team.run("Acme", None).decisions[1]
    assert (decision.chosen, decision.proposed) == ("analyst", proposed)


def test_handoff_the_limits_are_the_lists_themselves_and_a_handoff_cap(crm_tools, monkeypatch):
    import handoff_with_langgraph as module

    again = ai("", [tool_call("transfer_to_researcher", {})])
    bounded, _ = build(HandoffTeam, crm_tools, again, REC, APPROVE)
    assert (
        bounded.run("Acme", None).status == "completed"
    )  # a loop needs a list that allows it: here none does
    monkeypatch.setattr(module, "MAX_HANDOFFS", 2)
    capped, _ = build(HandoffTeam, crm_tools, again, REC, APPROVE)
    outcome = capped.run("Acme", None)
    assert (
        outcome.status == "stopped"
        and outcome.decisions[-1].reason == "a handoff limit was reached"
    )


def test_handoff_a_review_that_asks_for_a_revision_hands_back_to_the_analyst_once(crm_tools):
    team, _ = build(
        HandoffTeam,
        crm_tools,
        ai("", [tool_call("transfer_to_analyst", {})]),
        REC,
        REVISE,
        REC,
        REVISE,
    )
    outcome = team.run("Acme", None)
    assert outcome.specialists == [
        "crm_facts",
        "deals",
        "analyst",
        "reviewer",
        "analyst",
        "reviewer",
    ]
    assert outcome.decisions[-1].reason == "the review is done"


# What LangGraph did on its own (measured).


def test_measured_langgraphs_own_limit_is_10007_steps_so_every_limit_here_is_ours():
    from typing import TypedDict

    from langgraph.errors import GraphRecursionError
    from langgraph.graph import END, START, StateGraph

    class State(TypedDict, total=False):
        x: str

    runs = [0]

    def node(state):
        runs[0] += 1
        return {}

    graph = StateGraph(State)
    graph.add_node("a", node)
    graph.add_edge(START, "a")
    graph.add_conditional_edges("a", lambda s: "a", {"a": "a", END: END})
    with pytest.raises(GraphRecursionError):
        graph.compile().invoke({})
    assert runs[0] == 10007  # the library's default, against 25 in the Java LangGraph4j


def test_measured_a_child_graph_is_given_the_parents_state_and_its_value_wins_on_a_collision():
    from typing import TypedDict

    from langgraph.graph import START, StateGraph

    class State(TypedDict, total=False):
        x: str

    child = StateGraph(State)
    child.add_node("c", lambda s: {"x": f"child saw {s.get('x')}"})
    child.add_edge(START, "c")
    parent = StateGraph(State)
    parent.add_node("p", lambda s: {"x": "parent"})
    parent.add_node("team", child.compile())
    parent.add_edge(START, "p")
    parent.add_edge("p", "team")
    assert parent.compile().invoke({}) == {"x": "child saw parent"}


def test_measured_an_exception_raised_in_a_node_reaches_the_caller_unchanged_through_a_child_graph(
    crm_tools,
):
    team, _ = build(HierarchicalTeam, crm_tools)  # the first model call of the research team raises
    team._tools = crm_tools
    with pytest.raises(UnavailableError):
        team.run("Acme", None)
