"""The agent as a LangGraph `StateGraph`: gather, recommend, approval, act. The pause is
`interrupt()` inside the approval node and the checkpointer (`InMemorySaver`) keeps the state, so a
run is resumed with `Command(resume=...)` on the same thread id. Code decides the steps; the model
is called once, by the `recommend` node. Decisions and measurements: docs/adr/0041.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, TypedDict

from lab_common.agent import (
    DECLINED_MESSAGE,
    BoundedRuns,
    CompanyNotFoundError,
    NotAwaitingApprovalError,
    Outcome,
    Recommendation,
    UnknownRunError,
    outcome_for,
)
from lab_common.chat import UnavailableError
from lab_common.crm import CrmTools
from lab_common.recommender import Recommender
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class RunState(TypedDict, total=False):
    company: str
    model: str | None
    facts: str
    company_name: str
    action: str
    rationale: str
    approved: bool
    message: str


class LangGraphAgent:
    approach = "withLangGraph"

    def __init__(self, tools: CrmTools, recommender: Recommender) -> None:
        self._tools = tools
        self._recommender = recommender
        self._saver = InMemorySaver()
        self._graph = self._build()
        # a run is `None` while it waits and "completed" or "declined" afterwards
        self._runs: BoundedRuns[list[str | None]] = BoundedRuns(on_evict=self._saver.delete_thread)

    def _build(self):  # noqa: ANN202 - a compiled graph
        def gather(state: RunState) -> RunState:
            facts = self._tools.call("get_company_summary", state["company"])
            parsed = json.loads(facts)
            if parsed.get("status") != "executed":
                raise CompanyNotFoundError(f'No company matching "{state["company"]}" was found.')
            return {"facts": facts, "company_name": parsed["company"]["name"]}

        def recommend(state: RunState) -> RunState:
            rec = self._recommender.recommend(state["facts"], state.get("model"))
            return {"action": rec.action, "rationale": rec.rationale}

        def approval(state: RunState) -> RunState:
            # The run stops here until someone resumes it. On resume this node runs again from its
            # first line, and interrupt() returns the person's answer, so nothing before the call
            # may have a side effect.
            answer = interrupt({"action": state["action"], "rationale": state["rationale"]})
            return {"approved": bool(answer)}

        def act(state: RunState) -> RunState:
            # The only step with a consequence, and here a dry run: nothing is written anywhere.
            return {
                "message": "Approved. Dry run: this would create a follow-up task for "
                f"{state.get('company_name', 'the company')}: {state.get('action', '')} Nothing was written."
            }

        graph = StateGraph(RunState)
        graph.add_node("gather", gather)
        graph.add_node("recommend", recommend)
        graph.add_node("approval", approval)
        graph.add_node("act", act)
        graph.add_edge(START, "gather")
        graph.add_edge("gather", "recommend")
        graph.add_edge("recommend", "approval")
        graph.add_conditional_edges(
            "approval", lambda s: "act" if s.get("approved") else END, {"act": "act", END: END}
        )
        graph.add_edge("act", END)
        return graph.compile(checkpointer=self._saver)

    def _recommendation(self, run_id: str) -> Recommendation:
        values = self._graph.get_state({"configurable": {"thread_id": run_id}}).values
        return Recommendation(values.get("action", ""), values.get("rationale", ""))

    def start(self, company: str, model: str | None) -> Outcome:
        run_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": run_id}}
        try:
            result = self._graph.invoke({"company": company, "model": model}, config)
        except Exception:
            self._saver.delete_thread(run_id)
            raise
        if not result.get("__interrupt__"):
            self._saver.delete_thread(run_id)
            raise UnavailableError("The agent did not reach the approval step.")
        self._runs.put(run_id, [None])
        return outcome_for(run_id, "awaiting_approval", self._recommendation(run_id))

    def resume(self, run_id: str, approve: bool) -> Outcome:
        run = self._runs.get(run_id)
        if run is None:
            raise UnknownRunError(
                "No run with that id. It was never started, or it is no longer kept."
            )
        if run[0] is not None:
            raise NotAwaitingApprovalError(
                f"This run is not waiting for approval: it is already {run[0]}."
            )
        config: Any = {"configurable": {"thread_id": run_id}}
        final = self._graph.invoke(Command(resume=approve), config)
        run[0] = "completed" if approve else "declined"
        message = final.get("message", "") if approve else DECLINED_MESSAGE
        return outcome_for(run_id, run[0], self._recommendation(run_id), message)
