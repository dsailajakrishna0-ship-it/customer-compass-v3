"""The supervisor pattern on LangGraph: one coordinator decides who works next, after every step.

A manager who hands each job to a specialist and gets it back. After every job the supervisor node
looks at the state and decides who is next, **but the rule book (which specialists may be called
now) is code**, and the model only picks from the list that code gives. When only one specialist is
allowed nobody is asked. The graph: `supervisor`, the four specialists, an edge from each specialist
back to the supervisor and one conditional edge out of the supervisor. Decisions: docs/adr/0043.
"""

from __future__ import annotations

from typing import TypedDict

from lab_common.crm import CrmTools
from lab_common.team import (
    DEFAULT_MAX_TURNS,
    FINISH,
    SPECIALISTS,
    Context,
    Outcome,
    TeamModel,
    allowed,
)
from langgraph.graph import END, START, StateGraph


class TeamState(TypedDict, total=False):
    next: str  # the specialist the supervisor chose, or FINISH


class SupervisorTeam:
    approach = "withLangGraph"
    pattern = "supervisor"

    def __init__(
        self, tools: CrmTools, model: TeamModel, max_turns: int = DEFAULT_MAX_TURNS
    ) -> None:
        self._tools = tools
        self._model = model
        self._max_turns = max_turns

    def _graph(self, ctx: Context):  # noqa: ANN202 - a compiled graph
        def supervisor(state: TeamState) -> TeamState:
            if ctx.limit_reached():
                return {"next": FINISH}
            return {"next": ctx.choose(allowed(ctx.run))}

        def specialist(name: str):  # noqa: ANN202
            def node(state: TeamState) -> TeamState:
                ctx.work(name)
                return {}

            return node

        graph = StateGraph(TeamState)
        graph.add_node("supervisor", supervisor)
        for name in SPECIALISTS:
            graph.add_node(name, specialist(name))
            graph.add_edge(name, "supervisor")
        graph.add_edge(START, "supervisor")
        graph.add_conditional_edges(
            "supervisor",
            lambda state: state["next"],
            {**{name: name for name in SPECIALISTS}, FINISH: END},
        )
        return graph.compile()

    def run(self, company: str, model: str | None) -> Outcome:
        ctx = Context(self._tools, self._model, model, self._max_turns, company=company)
        self._graph(ctx).invoke({})
        return ctx.outcome()
