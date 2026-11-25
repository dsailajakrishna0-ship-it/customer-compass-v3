"""The handoff pattern on LangGraph: a relay, not a manager.

There is **no supervisor**. Each agent works, then **names the next agent** from **its own list**,
and control passes on; the agent that receives the work owns the next decision. The lists are code;
the model may only pick from them. The researcher's choice is a model call in which **each target is
a tool** (`transfer_to_analyst`); the call is read from the model's answer and **never executed**.
Decisions: docs/adr/0043.
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
    TeamModel,
)
from langgraph.graph import END, START, StateGraph

TRIAGE, RESEARCHER = "triage", "researcher"
MAX_HANDOFFS = 10
MAX_VISITS_PER_AGENT = 3
HANDOFF_PROMPT = (
    "You are the researcher of an account-review team. You have the facts. Decide who gets the work "
    "next by calling exactly one tool. Call transfer_to_analyst when you have enough, or "
    "transfer_to_researcher to look the deals up once more."
)


class TeamState(TypedDict, total=False):
    next: str


class HandoffTeam:
    approach = "withLangGraph"
    pattern = "handoff"

    def __init__(self, tools: CrmTools, model: TeamModel) -> None:
        self._tools = tools
        self._model = model

    def _graph(self, ctx: Context):  # noqa: ANN202
        visits: dict[str, int] = {}
        passes: list[tuple[str, str]] = []

        def hand_off(
            sender: str,
            options: list[str],
            chosen: str,
            reason: str,
            decided_by: str,
            proposed: str | None = None,
        ) -> TeamState:
            ctx.record(decided_by, options, chosen, reason, proposed)
            passes.append((sender, chosen))
            return {"next": chosen}

        def guard(name: str) -> TeamState | None:
            visits[name] = visits.get(name, 0) + 1
            repeated = len(passes) >= 4 and passes[-4:-2] == passes[-2:]
            if (
                len(ctx.decisions) >= MAX_HANDOFFS
                or visits[name] > MAX_VISITS_PER_AGENT
                or repeated
            ):
                ctx.run.stopped = True
                ctx.record("code", [FINISH], FINISH, "a handoff limit was reached")
                return {"next": FINISH}
            return None

        def triage(state: TeamState) -> TeamState:
            return hand_off(
                TRIAGE, [RESEARCHER], RESEARCHER, "the only agent triage may hand over to", "code"
            )

        def researcher(state: TeamState) -> TeamState:
            stopped = guard(RESEARCHER)
            if stopped:
                return stopped
            if not ctx.run.facts_loaded:
                ctx.work(CRM_FACTS)
            if ctx.run.company_not_found:
                return hand_off(RESEARCHER, [FINISH], FINISH, "the company was not found", "code")
            if ctx.run.deals_lookups < MAX_DEALS_LOOKUPS:
                ctx.work(DEALS)  # a visit looks the deals up while the limit allows
            options = [ANALYST] + (
                [RESEARCHER] if ctx.run.deals_lookups < MAX_DEALS_LOOKUPS else []
            )
            if len(options) == 1:
                return hand_off(
                    RESEARCHER, options, ANALYST, "only one hand-off is allowed", "code"
                )
            names = [f"transfer_to_{o}" for o in options]
            called = self._model.ask_tools(
                HANDOFF_PROMPT, "Decide who gets the work next.", ctx.model_name, names
            )
            chosen = called.removeprefix("transfer_to_") if called in names else None
            if chosen is None:
                proposed = (
                    called if called and called.replace("_", "").isalnum() else "no tool call"
                )
                return hand_off(
                    RESEARCHER,
                    options,
                    options[0],
                    "the answer was not an allowed hand-off; the first one was used",
                    "agent",
                    proposed,
                )
            return hand_off(RESEARCHER, options, chosen, "the researcher chose", "agent")

        def analyst(state: TeamState) -> TeamState:
            stopped = guard(ANALYST)
            if stopped:
                return stopped
            ctx.work(ANALYST)
            return hand_off(
                ANALYST,
                [REVIEWER],
                REVIEWER,
                "the analyst always hands over to the reviewer",
                "code",
            )

        def reviewer(state: TeamState) -> TeamState:
            stopped = guard(REVIEWER)
            if stopped:
                return stopped
            ctx.work(REVIEWER)
            run = ctx.run
            if run.approved or run.revisions >= MAX_REVISIONS:
                return hand_off(REVIEWER, [FINISH], FINISH, "the review is done", "code")
            return hand_off(
                REVIEWER, [ANALYST], ANALYST, "the reviewer asked for a revision", "agent"
            )

        graph = StateGraph(TeamState)
        for name, node in (
            (TRIAGE, triage),
            (RESEARCHER, researcher),
            (ANALYST, analyst),
            (REVIEWER, reviewer),
        ):
            graph.add_node(name, node)
        graph.add_edge(START, TRIAGE)
        mapping = {RESEARCHER: RESEARCHER, ANALYST: ANALYST, REVIEWER: REVIEWER, FINISH: END}
        for name in (TRIAGE, RESEARCHER, ANALYST, REVIEWER):
            graph.add_conditional_edges(name, lambda state: state["next"], mapping)
        return graph.compile()

    def run(self, company: str, model: str | None) -> Outcome:
        ctx = Context(self._tools, self._model, model, 10**6, company=company)
        self._graph(ctx).invoke({}, {"recursion_limit": 100})
        return ctx.outcome()
