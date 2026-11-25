"""The hierarchical pattern on LangGraph: supervisors of supervisors.

The same account review and the same four specialists, organised in **two teams**: a top supervisor
chooses between them, and each team is a LangGraph **child graph** (a compiled graph used as a node)
with a sub-supervisor of its own. What crosses a team boundary is the graph's state: a child is
given the parent's state and its final state is merged back, the child's value winning on a
collision, which is why each level has its own "who is next" key. Decisions: docs/adr/0043.
"""

from __future__ import annotations

from typing import TypedDict

from lab_common.crm import CrmTools
from lab_common.team import (
    ANALYST,
    CRM_FACTS,
    DEALS,
    FINISH,
    MAX_DEALS_LOOKUPS,
    MAX_REVISIONS,
    REVIEWER,
    Context,
    Outcome,
    Run,
    TeamModel,
)
from langgraph.graph import END, START, StateGraph

RESEARCH, ANSWER = "research_team", "answer_team"
MAX_TOP_TURNS = 4  # decisions of the top supervisor
MAX_TEAM_TURNS = 6  # decisions of one team's sub-supervisor
MAX_SPECIALIST_RUNS = 12  # the last net, over the whole run
MAX_RESEARCH_ROUNDS = 2


class TeamState(TypedDict, total=False):
    top_next: str  # the top supervisor's choice
    team_next: str  # the team supervisor's choice (the child's own key)
    research_rounds: int
    answered: bool


def top_allowed(run: Run, state: TeamState) -> list[str]:
    if run.company_not_found or state.get("answered"):
        return [FINISH]
    if not run.facts_loaded:
        return [RESEARCH]
    options = [ANSWER]
    if (
        run.deals_lookups < MAX_DEALS_LOOKUPS
        and state.get("research_rounds", 0) < MAX_RESEARCH_ROUNDS
    ):
        options.append(RESEARCH)
    return options


def research_allowed(run: Run) -> list[str]:
    if run.company_not_found:
        return [FINISH]
    if not run.facts_loaded:
        return [CRM_FACTS]
    return [FINISH, DEALS] if run.deals_lookups < MAX_DEALS_LOOKUPS else [FINISH]


def answer_allowed(run: Run) -> list[str]:
    if run.action is None:
        return [ANALYST]
    if not run.reviewed:
        return [REVIEWER]
    return [FINISH] if run.approved or run.revisions >= MAX_REVISIONS else [ANALYST]


class HierarchicalTeam:
    approach = "withLangGraph"
    pattern = "hierarchical"

    def __init__(self, tools: CrmTools, model: TeamModel) -> None:
        self._tools = tools
        self._model = model

    def _team(self, ctx: Context, name: str, members: list[str], rules, level: str):  # noqa: ANN001, ANN202
        """A child graph: a sub-supervisor and its members."""
        team_decisions = [0]

        def sub_supervisor(state: TeamState) -> TeamState:
            if team_decisions[0] >= MAX_TEAM_TURNS or len(ctx.specialists) >= MAX_SPECIALIST_RUNS:
                ctx.run.stopped = True
                ctx.record(
                    "code", [FINISH], FINISH, "the team's turn limit was reached", level=level
                )
                return {"team_next": FINISH}
            team_decisions[0] += 1
            return {"team_next": ctx.choose(rules(ctx.run), level=level)}

        def member(specialist: str):  # noqa: ANN202
            def node(state: TeamState) -> TeamState:
                ctx.work(specialist)
                return {}

            return node

        graph = StateGraph(TeamState)
        graph.add_node("sub_supervisor", sub_supervisor)
        for specialist in members:
            graph.add_node(specialist, member(specialist))
            graph.add_edge(specialist, "sub_supervisor")
        graph.add_edge(START, "sub_supervisor")
        graph.add_conditional_edges(
            "sub_supervisor",
            lambda state: state["team_next"],
            {**{m: m for m in members}, FINISH: END},
        )
        return graph.compile()

    def _graph(self, ctx: Context):  # noqa: ANN202
        research = self._team(ctx, RESEARCH, [CRM_FACTS, DEALS], research_allowed, "research")
        answer = self._team(
            ctx, ANSWER, [ANALYST, REVIEWER], lambda run: answer_allowed(run), "answer"
        )
        top_turns = [0]

        def top(state: TeamState) -> TeamState:
            if ctx.run.stopped:  # a team hit its limit: the whole run ends there
                ctx.record("code", [FINISH], FINISH, "a team was stopped at its limit", level="top")
                return {"top_next": FINISH}
            if top_turns[0] >= MAX_TOP_TURNS:
                ctx.run.stopped = True
                ctx.record(
                    "code",
                    [FINISH],
                    FINISH,
                    "the top supervisor's turn limit was reached",
                    level="top",
                )
                return {"top_next": FINISH}
            top_turns[0] += 1
            return {"top_next": ctx.choose(top_allowed(ctx.run, state), level="top")}

        def after_research(state: TeamState) -> TeamState:
            return {"research_rounds": state.get("research_rounds", 0) + 1}

        def after_answer(state: TeamState) -> TeamState:
            return {"answered": not ctx.run.stopped}

        graph = StateGraph(TeamState)
        graph.add_node("top", top)
        graph.add_node(RESEARCH, research)  # a compiled graph used as a node
        graph.add_node(ANSWER, answer)
        graph.add_node("after_research", after_research)
        graph.add_node("after_answer", after_answer)
        graph.add_edge(START, "top")
        graph.add_conditional_edges(
            "top",
            lambda state: state["top_next"],
            {RESEARCH: RESEARCH, ANSWER: ANSWER, FINISH: END},
        )
        graph.add_edge(RESEARCH, "after_research")
        graph.add_edge("after_research", "top")
        graph.add_edge(ANSWER, "after_answer")
        graph.add_edge("after_answer", "top")
        return graph.compile()

    def run(self, company: str, model: str | None) -> Outcome:
        ctx = Context(
            self._tools, self._model, model, 10**6, company=company
        )  # the limits are per level
        self._graph(ctx).invoke({})
        return ctx.outcome()
