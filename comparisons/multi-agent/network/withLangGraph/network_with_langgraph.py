"""The network pattern on LangGraph: a group chat of specialists with no manager.

When a peer has done its part, **it** says who should go next, and it may pick anyone, itself
included, or FINISH. Nobody builds a list of who is allowed; each peer only checks that it has what
it needs (an analyst with no facts does nothing), and a few blunt limits stop the chat from running
away: a turn limit, a visit limit per peer and a loop guard. **Nobody checks that the job is done**:
any peer may name FINISH at any time. Decisions: docs/adr/0043.
"""

from __future__ import annotations

from typing import TypedDict

from lab_common.crm import CrmTools
from lab_common.team import (
    ANALYST,
    CRM_FACTS,
    DEALS,
    DEFAULT_MAX_TURNS,
    FINISH,
    SPECIALISTS,
    Context,
    Outcome,
    TeamModel,
    parse_choice,
    supervisor_question,
)
from langgraph.graph import END, START, StateGraph

MAX_VISITS_PER_PEER = 3
LOOP_WINDOW = 3  # the same peer named this many times in a row, with nothing new, is a loop
NAMING_PROMPT = (
    "You are one specialist in an account-review team and you have finished your part. Name who "
    'should work next, yourself included, or FINISH. Reply with only a JSON object: {"next": '
    '"<one name from the list>", "reason": "<one short sentence>"}.'
)


class TeamState(TypedDict, total=False):
    next: str


def can_work(name: str, ctx: Context) -> bool:
    """A peer's own check: does it have what it needs?"""
    run = ctx.run
    if name == CRM_FACTS:
        return not run.facts_loaded
    if name in (DEALS, ANALYST):
        return run.facts_loaded
    return run.action is not None  # reviewer


class NetworkTeam:
    approach = "withLangGraph"
    pattern = "network"

    def __init__(
        self, tools: CrmTools, model: TeamModel, max_turns: int = DEFAULT_MAX_TURNS
    ) -> None:
        self._tools = tools
        self._model = model
        self._max_turns = max_turns

    def _graph(self, ctx: Context):  # noqa: ANN202
        visits: dict[str, int] = {}
        history: list[tuple[str, int]] = []  # (peer, progress when it was named)

        def stop(reason: str) -> TeamState:
            ctx.run.stopped = True
            ctx.record("code", [FINISH], FINISH, reason)
            return {"next": FINISH}

        def peer(name: str):  # noqa: ANN202
            def node(state: TeamState) -> TeamState:
                if len(ctx.decisions) >= self._max_turns:
                    return stop("the turn limit was reached")
                visits[name] = visits.get(name, 0) + 1
                if visits[name] > MAX_VISITS_PER_PEER:
                    return stop(f"{name} was named too often")
                if can_work(name, ctx):
                    ctx.work(name)
                history.append((name, ctx.run.progress))
                recent = history[-LOOP_WINDOW:]
                if (
                    len(recent) == LOOP_WINDOW
                    and len({p for p, _ in recent}) == 1
                    and len({g for _, g in recent}) == 1
                ):
                    return stop(f"{name} named itself again with nothing new")
                if len(history) >= 4:
                    a, b, c, d = (p for p, _ in history[-4:])
                    if a == c and b == d and a != b and len({g for _, g in history[-4:]}) == 1:
                        return stop(f"{a} and {b} named each other with nothing new")
                options = [*SPECIALISTS, FINISH]
                if ctx.run.company_not_found:
                    ctx.record(
                        "code",
                        [FINISH],
                        FINISH,
                        "the company was not found: nobody has anything to name",
                    )
                    return {"next": FINISH}
                answer = self._model.ask(
                    NAMING_PROMPT, supervisor_question(ctx.run, options), ctx.model_name
                )
                chosen, proposed, reason = parse_choice(answer, options)
                if chosen is None:
                    # no list built by code to fall back on: an unreadable naming ends the chat
                    ctx.record(
                        "peer",
                        options,
                        FINISH,
                        f"{name}'s answer was not a name from the list",
                        proposed,
                    )
                    return {"next": FINISH}
                ctx.record("peer", options, chosen, reason)
                return {"next": chosen}

            return node

        graph = StateGraph(TeamState)
        for name in SPECIALISTS:
            graph.add_node(name, peer(name))
        graph.add_edge(START, CRM_FACTS)  # the entry peer
        mapping = {**{name: name for name in SPECIALISTS}, FINISH: END}
        for name in SPECIALISTS:  # fully connected: every peer may name every peer
            graph.add_conditional_edges(name, lambda state: state["next"], mapping)
        return graph.compile()

    def run(self, company: str, model: str | None) -> Outcome:
        ctx = Context(self._tools, self._model, model, self._max_turns, company=company)
        self._graph(ctx).invoke({}, {"recursion_limit": 100})
        return ctx.outcome()
