"""A supervisor with specialist agents (a Python-edition extension, E3.1, ADR 0033; the twin of the Java
edition's E3, which is not part of the contract shared by the two editions).

Where the account follow-up agent (`workflow.py`) is a fixed pipeline, here a supervisor decides, turn by
turn, which specialist works next, and every specialist hands control back:

    START -> supervisor -> crm_facts | researcher | analyst | reviewer | drafter -> supervisor ... -> END

The supervisor is a model, so what it may choose is enforced in code: only specialists whose preconditions
hold are allowed; an unreadable or disallowed answer is replaced by the next step the fixed pipeline would
take; the researcher can only run so often; a run ends only when the task note exists (or no customer was
found). When only one specialist is allowed no model call is made at all. The specialists are the account
agent's own nodes (the same prompts, parsers, the reviewer's two code rules, the guard and the approval
gate) plus a researcher that searches every knowledge base (E1).

A completed run pauses at the same approval gate as `/agent/recommend`: nothing is written before the user
answers `POST /agent/confirm`.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app import tracing
from app.agent import agents, workflow
from app.agent.checkpoint import get_checkpointer
from app.agent.policies import AgentLimits, BudgetExceeded, RunBudget
from app.agent.workflow import AgentState, RunContext
from app.config import get_settings
from app.rag.knowledge_bases import all_knowledge_bases
from app.rag.multi_source import search_all

logger = logging.getLogger("app.agent.supervisor")

FINISH = "FINISH"
SPECIALISTS = ["crm_facts", "researcher", "analyst", "reviewer", "drafter"]
MAX_RESEARCH = 2  # how often the researcher may run in one request
RESEARCH_CHUNKS = 4  # chunks it asks every knowledge base for
STEPS_PER_TURN = 4  # the specialists' own steps are budgeted at this many per supervisor turn
RECURSION_LIMIT = 100  # LangGraph's own backstop; the turn limit is the real bound

SUPERVISOR_SYSTEM_PROMPT = """You are the Supervisor of a team of specialists that prepare an account follow-up for a CRM user.
Specialists:
- crm_facts: identifies the customer and loads CRM facts, open deals and recent interactions.
- researcher: searches the knowledge bases (customer documents and other handbooks) for background relevant to the request.
- analyst: proposes a next action, citing the evidence.
- reviewer: checks the analyst's proposal against the evidence.
- drafter: writes the follow-up task note for the user to confirm.
- FINISH: stop (only once the note is written or no customer was found).

Each turn you are told the state of the work and which choices are allowed now. Choose ONE from the allowed list. Use the researcher when more background would help the analyst; skip it when the CRM facts already answer the request.
Reply with JSON only, no other text:
{"next": "<name>", "reason": "<one short sentence>"}"""


class SupervisorState(AgentState, total=False):
    """The account agent's state plus what the supervisor keeps: its decisions and how often each
    specialist has run. Plain data only."""

    next: str  # the specialist chosen for this turn, or FINISH
    turns: list[
        dict
    ]  # every decision: {"turn", "next", "source", "reason", "allowed", "proposed"?}
    ran: dict  # specialist name -> how many times it has run
    rec_version: (
        int  # counts the analyst's proposals, so a review is known to be of the current one
    )
    review_version: int  # which proposal the stored review is of


@dataclass(frozen=True)
class Proposal:
    """What the model proposed (`next` is None when its answer could not be read) and why."""

    next: str | None
    reason: str = ""


# ------------------------------------------------------------------------------------ rules (code)


def _ran(state: SupervisorState, specialist: str) -> int:
    return int(state.get("ran", {}).get(specialist, 0))


def _counted(state: SupervisorState, specialist: str) -> dict:
    return {**state.get("ran", {}), specialist: _ran(state, specialist) + 1}


def _review_current(state: SupervisorState) -> bool:
    """True when the stored review is of the current recommendation (not an earlier one)."""
    return state.get("review_version", -1) == state.get("rec_version", 0)


def allowed(state: SupervisorState, max_revisions: int) -> list[str]:
    """The specialists that may run now, the fixed pipeline's next step first. Preconditions are code:
    the analyst needs evidence, the reviewer a recommendation, the drafter a reviewed recommendation that
    was approved or is out of revisions; FINISH needs the note (or no customer found)."""
    if _ran(state, "crm_facts") == 0:
        return ["crm_facts"]  # nothing else is possible before the customer is known
    if not state.get("company"):
        return [FINISH]  # no customer found: stop
    if state.get("task_note"):
        return [FINISH]
    research = _ran(state, "researcher") < MAX_RESEARCH
    if "recommendation" not in state:
        return ["analyst", *(["researcher"] if research else [])]
    reviewed = "review" in state and _review_current(state)
    if not reviewed:
        return ["reviewer"]
    approved = state["review"]["verdict"] == "approve"
    if approved or state.get("revisions", 0) >= max_revisions:
        return ["drafter"]
    # sent back by the reviewer: another try, with its reasons
    return ["analyst", *(["researcher"] if research else [])]


def parse_proposal(reply: str) -> Proposal:
    data = agents.parse_json_object(reply)
    if not data or not isinstance(data.get("next"), str):
        return Proposal(None)
    reason = data.get("reason")
    return Proposal(data["next"].strip(), reason if isinstance(reason, str) else "")


def _summary(state: SupervisorState) -> str:
    company = state.get("company")
    recommendation = state.get("recommendation")
    review = state.get("review")
    return "\n".join(
        [
            f"- customer: {company['name'] if company else 'not identified yet'}",
            f"- evidence items: {len(state.get('evidence', []))}",
            f"- researcher runs: {_ran(state, 'researcher')}",
            f"- recommendation: {recommendation['action'] if recommendation else 'none yet'}",
            "- review: "
            + (
                f"{review['verdict']} {review['reasons']}"
                if review and _review_current(state)
                else "none yet"
            ),
            "- kind of request: an account follow-up",
            f"- task note: {'written' if state.get('task_note') else 'not written'}",
        ]
    )


# ------------------------------------------------------------------------------------ the supervisor


async def supervisor(state: SupervisorState, config: RunnableConfig) -> SupervisorState:
    """One turn: work out what is allowed, ask the model when there is a choice, enforce the rules."""
    ctx = workflow._ctx(config)
    settings = get_settings()
    turns = list(state.get("turns", []))
    if len(turns) >= settings.supervisor_max_turns:
        raise BudgetExceeded(f"turn limit reached ({settings.supervisor_max_turns})")
    ctx.budget.spend()
    started = time.monotonic()
    choices = allowed(state, ctx.limits.max_revisions)
    chosen = choices[0]  # the next step of the fixed pipeline comes first
    source = "code"
    reason = "only one choice allowed" if len(choices) == 1 else ""
    proposed: str | None = None
    if len(choices) > 1:
        proposal = await _ask(state, ctx, choices)
        if proposal.next is not None and proposal.next in choices:
            chosen, source, reason = proposal.next, "supervisor", proposal.reason
        else:
            proposed = proposal.next
            reason = (
                "the supervisor's answer could not be read; the pipeline's next step was used"
                if proposal.next is None
                else f'"{proposal.next}" is not allowed now; the pipeline\'s next step was used'
            )
    turn: dict[str, Any] = {
        "turn": len(turns) + 1,
        "next": chosen,
        "source": source,
        "reason": reason,
        "allowed": choices,
    }
    if proposed is not None:
        turn["proposed"] = proposed
    turns.append(turn)
    ctx.trace.record("supervisor", "supervisor", ", ".join(choices), f"{chosen}: {reason}", started)
    return {"next": chosen, "turns": turns}


async def _ask(state: SupervisorState, ctx: RunContext, choices: list[str]) -> Proposal:
    prompt = (
        f"Request: {state['message']}\n\nState of the work:\n{_summary(state)}\n\n"
        f"Allowed now: {', '.join(choices)}"
    )
    result = await ctx.llm(
        "supervisor", SUPERVISOR_SYSTEM_PROMPT, [{"role": "user", "content": prompt}]
    )
    ctx.note_call("supervisor", result)
    return parse_proposal(result.content)


def after_supervisor(state: SupervisorState) -> str:
    return state.get("next", FINISH)


# ------------------------------------------------------------------------------------ the specialists


async def crm_facts(state: SupervisorState, config: RunnableConfig) -> SupervisorState:
    """Identify the customer and load its facts, deals and interactions (the account agent's two nodes)."""
    update: dict[str, Any] = dict(await workflow.classify(state, config))
    if update.get("company"):
        merged: dict[str, Any] = {**state, **update}
        update.update(await workflow.evidence(merged, config))  # type: ignore[arg-type]
    update["ran"] = _counted(state, "crm_facts")
    return update  # type: ignore[return-value]


async def researcher(state: SupervisorState, config: RunnableConfig) -> SupervisorState:
    """Search every knowledge base for background; chunks already in the evidence are skipped. A second
    visit also looks for what the reviewer found missing."""
    ctx = workflow._ctx(config)
    ctx.budget.spend()
    started = time.monotonic()
    query = state["message"]
    review = state.get("review")
    if review and review["reasons"]:
        query = f"{query} {' '.join(review['reasons'])}"
    found = await search_all(query, all_knowledge_bases(), RESEARCH_CHUNKS)
    items = list(state["evidence"])
    findings = list(state["findings"])
    existing = {item["text"] for item in items}
    added = 0
    for kb_chunk in found:
        text = kb_chunk.chunk.content
        if text in existing:
            continue
        title = f"[{kb_chunk.knowledge_base}] {kb_chunk.chunk.document_title}"
        workflow._add_item(
            items, findings, f"document: {title}", text, f"document: {title}", scan=True
        )
        existing.add(text)
        added += 1
    sources = sorted({c.knowledge_base for c in found})
    ctx.trace.record(
        "tool", "search_knowledge_bases", query, f"{added} new chunk(s) from {sources}", started
    )
    return {"evidence": items, "findings": findings, "ran": _counted(state, "researcher")}


async def analyst(state: SupervisorState, config: RunnableConfig) -> SupervisorState:
    """The analyst proposes (or, after a "revise", proposes again with the reviewer's reasons)."""
    update: dict[str, Any] = {}
    current: dict[str, Any] = dict(state)
    if "recommendation" in state:
        update.update(
            await workflow.prepare_revision(state)
        )  # revisions + 1 and the reviewer's reasons
        current.update(update)
    update.update(await workflow.analyze(current, config))  # type: ignore[arg-type]
    update["rec_version"] = state.get("rec_version", 0) + 1
    update["ran"] = _counted(state, "analyst")
    return update  # type: ignore[return-value]


async def reviewer(state: SupervisorState, config: RunnableConfig) -> SupervisorState:
    update: dict[str, Any] = dict(await workflow.review(state, config))
    update["review_version"] = state.get("rec_version", 0)
    update["ran"] = _counted(state, "reviewer")
    return update  # type: ignore[return-value]


async def drafter(state: SupervisorState, config: RunnableConfig) -> SupervisorState:
    update: dict[str, Any] = dict(await workflow.draft(state, config))
    update["ran"] = _counted(state, "drafter")
    return update  # type: ignore[return-value]


def build_graph():
    """The supervisor and its specialists. It holds no per-run state (the run's context travels in the
    config), so it is compiled once."""
    graph = StateGraph(SupervisorState)
    graph.add_node("supervisor", supervisor)
    nodes = {
        "crm_facts": crm_facts,
        "researcher": researcher,
        "analyst": analyst,
        "reviewer": reviewer,
        "drafter": drafter,
    }
    for name, node in nodes.items():
        graph.add_node(name, node)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor", after_supervisor, {**{name: name for name in SPECIALISTS}, FINISH: END}
    )
    for name in SPECIALISTS:
        graph.add_edge(name, "supervisor")  # every specialist hands control back
    return graph.compile()


_GRAPH = build_graph()


# ------------------------------------------------------------------------------------ entry point


def _view(final: dict[str, Any]) -> dict:
    turns = final.get("turns", [])
    model_decisions = sum(1 for t in turns if t["source"] == "supervisor")
    return {
        "turns": turns,
        "modelDecisions": model_decisions,
        "codeDecisions": len(turns) - model_decisions,
    }


async def run_supervised(
    message: str,
    llm: agents.LlmCall,
    limits: AgentLimits | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> dict:
    """One supervised run, as one span (Stage 5.1), with the account agent's response shape plus a
    `supervisor` object holding every decision. It never writes: a completed run pauses at the same
    approval gate, and `POST /agent/confirm` resumes it."""
    limits = limits or AgentLimits.from_env()
    with tracing.span(
        "agent.supervise",
        "agent",
        {
            "agent.max_steps": limits.max_steps,
            "agent.timeout_seconds": limits.timeout_seconds,
            "agent.request_chars": len(message),
            "langfuse.observation.input": message if tracing.capture_content() else None,
        },
    ) as span:
        result = await _run(message, llm, limits, checkpointer)
        decisions = result.get("supervisor", {})
        span.set(
            {
                "agent.status": result["status"],
                "agent.steps": len(result["trace"]),
                "agent.llm_calls": len(result.get("llmCalls", [])),
                "agent.supervisor_turns": len(decisions.get("turns", [])),
            }
        )
        if result["status"] in ("timed_out", "budget_exceeded"):
            span.fail(result["status"])
        return result


async def _run(
    message: str, llm: agents.LlmCall, limits: AgentLimits, checkpointer: BaseCheckpointSaver | None
) -> dict:
    # the step budget counts the specialists' steps; the turn limit counts the supervisor's turns
    budget_limits = AgentLimits(
        max_steps=get_settings().supervisor_max_turns * STEPS_PER_TURN,
        timeout_seconds=limits.timeout_seconds,
        max_revisions=limits.max_revisions,
    )
    ctx = RunContext(llm=llm, limits=limits, budget=RunBudget(budget_limits))
    try:
        async with asyncio.timeout(limits.timeout_seconds):
            final = await _GRAPH.ainvoke(
                {"message": message},
                config={"configurable": {"ctx": ctx}, "recursion_limit": RECURSION_LIMIT},
            )
            if final["status"] == "completed":
                await workflow._pause_at_gate(final, ctx, checkpointer or await get_checkpointer())
    except TimeoutError:
        return workflow._response(
            "timed_out", ctx.trace, message=f"Stopped after {limits.timeout_seconds:.0f}s."
        )
    except BudgetExceeded as exc:
        return workflow._response("budget_exceeded", ctx.trace, message=str(exc))
    result = workflow._build_result(final, ctx)
    result["supervisor"] = _view(final)
    return result
