"""Stage 10 workflow as a LangGraph graph: the "Account Follow-up Recommender".

The same steps as before (Stage 3.2a only changes how they are wired, not what they do):

  classify -> evidence -> documents -> analyze <-> review -> draft -> human_approval

Each box is a node: a plain async function that reads the run's state and returns the pieces it
changed. The edges, including the one loop (review can send analyze back once), are declared in
`build_graph()`, so the shape of the agent is visible in one place instead of inside a `while`.

What stays in code, never in a prompt: the step and time limits (`RunBudget`), the guardrails and
the rule that nothing is written here. Creating a task happens only in the separate confirm
step (routes/agent.py). The graph ends at `human_approval` and does not write.

State holds plain data only (dicts, lists, strings). Anything process-local that must survive an
exception, such as the trace and the step budget, lives in `RunContext` instead, so a run that is
stopped by a limit still reports every step it took.
"""

import asyncio
import functools
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agent import agents
from app.agent.checkpoint import get_checkpointer, thread_id
from app.agent.policies import AgentLimits, BudgetExceeded, RunBudget
from app.agent.trace import Trace
from app.chat.router import find_mentioned_company
from app.crm.queries import get_recent_interactions, list_companies
from app.guardrails.audit import record_events
from app.guardrails.llm_guard import guard_input
from app.guardrails.prompt_guard import (
    UNTRUSTED_CONTEXT_INSTRUCTION,
    GuardFinding,
    add_findings,
    build_report,
    scan_and_neutralize,
    scan_output,
    wrap_untrusted_context,
)
from app.mcp.tools import (
    create_followup_task_tool,
    get_company_summary_tool,
    search_documents_tool,
)

logger = logging.getLogger("app.agent.workflow")

MAX_DEALS, MAX_INTERACTIONS, MAX_DOCS = 3, 5, 3
RECURSION_LIMIT = 30  # LangGraph's own backstop; a normal run takes 9 steps at most


class AgentState(TypedDict, total=False):
    """Everything the graph remembers between nodes. Plain data only."""

    message: str
    question_finding: dict  # the guarded request: {neutralized_text, matched_patterns, ...}
    company: dict | None  # {"id", "name"}; None when the request names no CRM company
    company_names: list[str]  # every CRM company, for the cross-customer output scan
    evidence: list[dict]  # [{"label": "E1", "source": ..., "text": ...}, ...]
    findings: list[dict]  # guard findings on stored text: {"location", ...GuardFinding fields}
    recommendation: dict  # {"action", "rationale", "evidence", "structured"}
    review: dict  # {"verdict", "reasons"}
    feedback: list[str] | None  # the reviewer's reasons, handed back to the analyst
    revisions: int
    task_note: str
    output_findings: dict  # {"action", "rationale", "note"} each a GuardFinding as a dict
    flagged: dict  # {"flagged": bool, "reasons": [...]}
    status: str  # "completed" or "company_not_found"
    approved: bool  # the user's answer at the gate
    result: dict  # what the write node returned


@dataclass
class RunContext:
    """Process-local helpers for one run. Not part of the state: they hold the model call, the
    limits and the trace, none of which can be saved, and the trace must outlive an exception."""

    llm: agents.LlmCall
    limits: AgentLimits
    budget: RunBudget
    trace: Trace = field(default_factory=Trace)
    llm_calls: list[dict] = field(default_factory=list)

    def note_call(self, agent: str, result) -> None:
        self.llm_calls.append(
            {
                "agent": agent,
                "model": result.model,
                "latencyMs": result.latency_ms,
                "fallbackUsed": result.fallback_used,
            }
        )


def _ctx(config: RunnableConfig) -> RunContext:
    return config["configurable"]["ctx"]


def _finding_dict(finding: GuardFinding, location: str | None = None) -> dict:
    data = asdict(finding)
    if location is not None:
        data["location"] = location
    return data


def _finding(data: dict) -> GuardFinding:
    return GuardFinding(
        neutralized_text=data["neutralized_text"],
        matched_patterns=list(data["matched_patterns"]),
        matched_snippets=list(data["matched_snippets"]),
    )


def _add_item(
    items: list[dict], findings: list[dict], source: str, text: str, location: str, scan: bool
) -> None:
    """Adds one labelled evidence item (E1, E2, ...). Items that came from stored text are
    scanned and neutralized before any agent sees them."""
    if scan:
        finding = scan_and_neutralize(text)
        text = finding.neutralized_text
        if finding.matched_patterns:
            findings.append(_finding_dict(finding, location))
    items.append({"label": f"E{len(items) + 1}", "source": source, "text": text})


def _evidence_text(items: list[dict]) -> str:
    lines = "".join(f"{i['label']} [{i['source']}] {i['text']}\n" for i in items)
    return UNTRUSTED_CONTEXT_INSTRUCTION + "\n" + wrap_untrusted_context(lines.strip())


# ------------------------------------------------------------------------------------ nodes


async def classify(state: AgentState, config: RunnableConfig) -> AgentState:
    """Guard the request and find which CRM company it is about."""
    ctx = _ctx(config)
    started = time.monotonic()
    question_finding = await guard_input(state["message"])
    companies = await list_companies()
    company = find_mentioned_company(question_finding.neutralized_text, companies)
    ctx.trace.record(
        "code",
        "identify_company",
        state["message"],
        company.name if company else "no company found",
        started,
        status="ok" if company else "error",
    )
    return {
        "question_finding": _finding_dict(question_finding),
        "company": {"id": company.id, "name": company.name} if company else None,
        "company_names": [c.name for c in companies],
        "status": "completed" if company else "company_not_found",
    }


def _company(state: AgentState) -> dict:
    """The company the run is about. Every node after `classify` runs only when one was found."""
    company = state["company"]
    assert company is not None
    return company


def after_classify(state: AgentState) -> str:
    return "evidence" if state["company"] else END


async def evidence(state: AgentState, config: RunnableConfig) -> AgentState:
    """Evidence steps 1 and 2: CRM facts and deals (a tool), then recent interactions (code)."""
    ctx = _ctx(config)
    name, company_id = _company(state)["name"], _company(state)["id"]
    items: list[dict] = []
    findings: list[dict] = []

    ctx.budget.spend()
    started = time.monotonic()
    summary = await get_company_summary_tool(name)
    company = summary.get("company", {})
    _add_item(
        items,
        findings,
        "CRM facts",
        f"{company.get('name')}: industry {company.get('industry')}, status {company.get('relationshipStatus')}, "
        f"{company.get('wonDealsCount')} won / {company.get('lostDealsCount')} lost deals.",
        "tool: get_company_summary",
        scan=False,
    )
    for deal in company.get("openDeals", [])[:MAX_DEALS]:
        _add_item(
            items,
            findings,
            "open deal",
            f"{deal['name']}, {deal['amount']}, expected close {deal['expectedCloseDate']}.",
            "tool: get_company_summary",
            scan=False,
        )
    ctx.trace.record("tool", "get_company_summary", name, f"{len(items)} evidence item(s)", started)

    ctx.budget.spend()
    started = time.monotonic()
    interactions = await get_recent_interactions(company_id, MAX_INTERACTIONS)
    before = len(items)
    for item in interactions:
        _add_item(
            items,
            findings,
            f"{item.interaction_type} {item.occurred_at[:10]}",
            f"{item.subject}: {item.summary}",
            f"interaction: {item.subject}",
            scan=True,
        )
    ctx.trace.record(
        "code", "get_recent_interactions", name, f"{len(items) - before} interaction(s)", started
    )
    return {"evidence": items, "findings": findings}


async def documents(state: AgentState, config: RunnableConfig) -> AgentState:
    """Evidence step 3: search the ingested documents for this company."""
    ctx = _ctx(config)
    name = _company(state)["name"]
    items = list(state["evidence"])
    findings = list(state["findings"])

    ctx.budget.spend()
    started = time.monotonic()
    docs = await search_documents_tool("recent history, requests and open issues", name)
    before = len(items)
    for doc in docs.get("results", [])[:MAX_DOCS]:
        _add_item(
            items,
            findings,
            f"document: {doc['title']}",
            doc["content"],
            f"document: {doc['title']}",
            scan=True,
        )
    ctx.trace.record(
        "tool", "search_documents", name, f"{len(items) - before} document chunk(s)", started
    )
    return {"evidence": items, "findings": findings}


async def analyze(state: AgentState, config: RunnableConfig) -> AgentState:
    """The Analyst agent proposes a next action (again, with the reviewer's reasons, on a revision)."""
    ctx = _ctx(config)
    revisions = state.get("revisions", 0)
    ctx.budget.spend()
    started = time.monotonic()
    recommendation, result = await agents.run_analyst(
        ctx.llm, _evidence_text(state["evidence"]), state.get("feedback")
    )
    ctx.note_call("analyst", result)
    ctx.trace.record(
        "agent",
        "Analyst agent" + (" (revision)" if revisions else ""),
        f"{len(state['evidence'])} evidence item(s)",
        recommendation.action,
        started,
    )
    return {"recommendation": asdict(recommendation)}


async def review(state: AgentState, config: RunnableConfig) -> AgentState:
    """The Reviewer agent checks the proposal. Code adds two rules no model can waive."""
    ctx = _ctx(config)
    recommendation = agents.Recommendation(**state["recommendation"])
    labels = {item["label"] for item in state["evidence"]}
    ctx.budget.spend()
    started = time.monotonic()
    verdict, result = await agents.run_reviewer(
        ctx.llm, _evidence_text(state["evidence"]), recommendation
    )
    ctx.note_call("reviewer", result)
    unknown = agents.unknown_citations(recommendation, labels)
    if unknown:
        verdict = agents.Review(
            "revise",
            [*verdict.reasons, f"Cited evidence that does not exist: {', '.join(unknown)}"],
        )
    elif not recommendation.evidence:
        verdict = agents.Review("revise", [*verdict.reasons, "No evidence was cited."])
    ctx.trace.record(
        "agent",
        "Reviewer agent",
        recommendation.action,
        f"{verdict.verdict}: {'; '.join(verdict.reasons)}",
        started,
    )
    return {"review": asdict(verdict)}


def after_review(state: AgentState, config: RunnableConfig) -> str:
    """Approved, or out of revisions: go on. Otherwise send the analyst back with the reasons."""
    if state["review"]["verdict"] == "approve":
        return "draft"
    if state.get("revisions", 0) >= _ctx(config).limits.max_revisions:
        return "draft"
    return "revise"


async def prepare_revision(state: AgentState) -> AgentState:
    return {"revisions": state.get("revisions", 0) + 1, "feedback": state["review"]["reasons"]}


async def draft(state: AgentState, config: RunnableConfig) -> AgentState:
    """The Task Drafter writes the follow-up note, then the output guard scans every text the user
    will see (same cross-customer and leak scan the chat routes use)."""
    ctx = _ctx(config)
    recommendation = agents.Recommendation(**state["recommendation"])
    company_name = _company(state)["name"]
    ctx.budget.spend()
    started = time.monotonic()
    task_note, result = await agents.run_task_drafter(ctx.llm, recommendation)
    ctx.note_call("task_drafter", result)
    ctx.trace.record("agent", "Task Drafter agent", recommendation.action, task_note, started)

    names = state["company_names"]
    action = scan_output(recommendation.action, company_name, names)
    rationale = scan_output(recommendation.rationale, company_name, names)
    note = scan_output(task_note, company_name, names)
    report = build_report(
        (_finding(state["question_finding"]), "user_input"),
        *[(_finding(f), f["location"]) for f in state["findings"]],
    )
    report = add_findings(
        report,
        (action, "output: recommendation"),
        (rationale, "output: rationale"),
        (note, "output: task note"),
    )
    if report.flagged:
        logger.warning("prompt_guard_flagged agent %s", report.reasons)
        await record_events("agent", report.events)
    return {
        "task_note": task_note,
        "output_findings": {
            "action": _finding_dict(action),
            "rationale": _finding_dict(rationale),
            "note": _finding_dict(note),
        },
        "flagged": {"flagged": report.flagged, "reasons": report.reasons},
    }


async def human_approval(state: AgentState, config: RunnableConfig) -> AgentState:
    """The gate. The run stops here and is saved to Postgres; nothing is written. It continues only
    when /agent/confirm resumes it with the user's answer ({"confirm": true or false})."""
    note = _finding(state["output_findings"]["note"])
    ctx = config["configurable"].get("ctx")
    if ctx is not None:  # absent when the run is resumed later: the first request already traced it
        ctx.trace.record(
            "gate",
            "awaiting_user_confirmation",
            "task not created",
            f"proposed: {note.neutralized_text}",
            time.monotonic(),
        )
    answer = interrupt({"proposedNote": note.neutralized_text})
    return {"approved": bool(answer.get("confirm"))}


def after_approval(state: AgentState) -> str:
    return "write" if state.get("approved") else END


async def write(state: AgentState) -> AgentState:
    """The only node that changes anything: creates the task the user approved."""
    company = _company(state)["name"]
    note = _finding(state["output_findings"]["note"]).neutralized_text
    return {"result": await create_followup_task_tool(company, note, confirm=True)}


def build_graph():
    """Part 1 of the agent: from the question to a drafted note. It holds no per-run state, so it is
    compiled once. It has no checkpointer: the run is only worth saving once it reaches the gate."""
    graph = StateGraph(AgentState)
    graph.add_node("classify", classify)
    graph.add_node("evidence", evidence)
    graph.add_node("documents", documents)
    graph.add_node("analyze", analyze)
    graph.add_node("review", review)
    graph.add_node("prepare_revision", prepare_revision)
    graph.add_node("draft", draft)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", after_classify, ["evidence", END])
    graph.add_edge("evidence", "documents")
    graph.add_edge("documents", "analyze")
    graph.add_edge("analyze", "review")
    graph.add_conditional_edges(
        "review", after_review, {"draft": "draft", "revise": "prepare_revision"}
    )
    graph.add_edge("prepare_revision", "analyze")
    graph.add_edge("draft", END)
    return graph.compile()


def build_approval_graph(checkpointer: BaseCheckpointSaver | None = None):
    """Part 2: the gate and the write. It starts from part 1's finished state, stops at
    `human_approval` and is saved under a thread id that /agent/confirm can derive again.

    It is a second small graph because the thread id comes from the drafted note, which does not
    exist until part 1 has run (ADR 0018, amended in 3.2b)."""
    graph = StateGraph(AgentState)
    graph.add_node("human_approval", human_approval)
    graph.add_node("write", write)
    graph.add_edge(START, "human_approval")
    graph.add_conditional_edges("human_approval", after_approval, ["write", END])
    graph.add_edge("write", END)
    return graph.compile(checkpointer=checkpointer)


_GRAPH = build_graph()


@functools.cache
def _approval_graph(checkpointer: BaseCheckpointSaver):
    return build_approval_graph(checkpointer)


# ------------------------------------------------------------------------------ entry point


def _response(status: str, trace: Trace, **extra) -> dict:
    return {"route": "agent", "status": status, "trace": trace.to_list(), **extra}


async def run_account_review(
    message: str,
    llm: agents.LlmCall,
    limits: AgentLimits | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> dict:
    limits = limits or AgentLimits.from_env()
    ctx = RunContext(llm=llm, limits=limits, budget=RunBudget(limits))
    try:
        async with asyncio.timeout(limits.timeout_seconds):
            final = await _GRAPH.ainvoke(
                {"message": message},
                config={"configurable": {"ctx": ctx}, "recursion_limit": RECURSION_LIMIT},
            )
            if final["status"] == "completed":
                await _pause_at_gate(final, ctx, checkpointer or await get_checkpointer())
    except TimeoutError:
        return _response(
            "timed_out", ctx.trace, message=f"Stopped after {limits.timeout_seconds:.0f}s."
        )
    except BudgetExceeded as exc:
        return _response("budget_exceeded", ctx.trace, message=str(exc))
    return _build_result(final, ctx)


def _thread_config(final: dict[str, Any]) -> dict:
    note = final["output_findings"]["note"]["neutralized_text"]
    return {"configurable": {"thread_id": thread_id(final["company"]["name"], note)}}


async def _pause_at_gate(
    final: dict[str, Any], ctx: RunContext, saver: BaseCheckpointSaver
) -> None:
    """Runs the gate: the run stops at `human_approval` and is saved in Postgres."""
    config = _thread_config(final)
    config["configurable"]["ctx"] = ctx
    await _approval_graph(saver).ainvoke(final, config=config)


async def resume_run(
    company_name: str, note: str, confirm: bool, checkpointer: BaseCheckpointSaver | None = None
) -> dict | None:
    """Continues a paused run with the user's answer. Returns what `/agent/confirm` should answer, or
    None when no paused run matches (a restart without a saved run, an edited note, an unknown name),
    in which case the caller writes directly, as it did before 3.2b."""
    graph = _approval_graph(checkpointer or await get_checkpointer())
    config = {"configurable": {"thread_id": thread_id(company_name, note)}}
    snapshot = await graph.aget_state(config)
    if snapshot.next != ("human_approval",):
        return None
    final = await graph.ainvoke(Command(resume={"confirm": confirm}), config=config)
    return final["result"] if confirm else {"status": "declined", "message": "No task was created."}


def _build_result(final: dict[str, Any], ctx: RunContext) -> dict:
    if final["status"] == "company_not_found":
        return _response(
            "company_not_found", ctx.trace, message="Name a company from the CRM to analyze."
        )
    company = final["company"]
    guarded = final["output_findings"]
    return _response(
        "completed",
        ctx.trace,
        company={"id": company["id"], "name": company["name"]},
        evidence=final["evidence"],
        recommendation={
            "action": guarded["action"]["neutralized_text"],
            "rationale": guarded["rationale"]["neutralized_text"],
            "evidence": final["recommendation"]["evidence"],
        },
        review={
            "approved": final["review"]["verdict"] == "approve",
            "verdict": final["review"]["verdict"],
            "reasons": final["review"]["reasons"],
            "revisions": final.get("revisions", 0),
        },
        proposedTask={"companyName": company["name"], "note": guarded["note"]["neutralized_text"]},
        guardrail=final["flagged"],
        llmCalls=ctx.llm_calls,
    )
