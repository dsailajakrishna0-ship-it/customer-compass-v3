"""Stage 10 workflow: the code-controlled "Account Follow-up Recommender".

This module (plain code, no LLM) decides the order of steps:

  find company -> gather evidence (3 steps) -> Analyst agent -> Reviewer agent
  -> [Analyst revises once if sent back] -> Task Drafter agent
  -> stop and wait for the user to confirm

It composes existing capabilities instead of re-implementing them: the Stage 9
tools for CRM facts and document search, the Stage 5 CRM queries, and the
Stage 8 guardrails. It never creates a task; that happens only in the
separate confirm step (see routes/agent.py).
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.agent import agents
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
from app.mcp.tools import get_company_summary_tool, search_documents_tool

logger = logging.getLogger("app.agent.workflow")

MAX_DEALS, MAX_INTERACTIONS, MAX_DOCS = 3, 5, 3


@dataclass
class EvidenceBundle:
    text: str
    items: list[dict] = field(default_factory=list)
    findings: list[tuple[GuardFinding, str]] = field(default_factory=list)


def _add_item(bundle: EvidenceBundle, source: str, text: str, location: str, scan: bool) -> None:
    """Adds one labelled evidence item (E1, E2, ...). Items that came from
    stored text are scanned and neutralized before any agent sees them."""
    if scan:
        finding = scan_and_neutralize(text)
        text = finding.neutralized_text
        if finding.matched_patterns:
            bundle.findings.append((finding, location))
    label = f"E{len(bundle.items) + 1}"
    bundle.items.append({"label": label, "source": source, "text": text})
    bundle.text += f"{label} [{source}] {text}\n"


async def _gather_evidence(company_name: str, company_id: int, budget: RunBudget, trace: Trace) -> EvidenceBundle:
    bundle = EvidenceBundle(text="")

    budget.spend()
    started = time.monotonic()
    summary = await get_company_summary_tool(company_name)
    company = summary.get("company", {})
    _add_item(
        bundle,
        "CRM facts",
        f"{company.get('name')}: industry {company.get('industry')}, status {company.get('relationshipStatus')}, "
        f"{company.get('wonDealsCount')} won / {company.get('lostDealsCount')} lost deals.",
        "tool: get_company_summary",
        scan=False,
    )
    for deal in company.get("openDeals", [])[:MAX_DEALS]:
        _add_item(
            bundle,
            "open deal",
            f"{deal['name']}, {deal['amount']}, expected close {deal['expectedCloseDate']}.",
            "tool: get_company_summary",
            scan=False,
        )
    trace.record("tool", "get_company_summary", company_name, f"{len(bundle.items)} evidence item(s)", started)

    budget.spend()
    started = time.monotonic()
    interactions = await get_recent_interactions(company_id, MAX_INTERACTIONS)
    before = len(bundle.items)
    for item in interactions:
        _add_item(
            bundle,
            f"{item.interaction_type} {item.occurred_at[:10]}",
            f"{item.subject}: {item.summary}",
            f"interaction: {item.subject}",
            scan=True,
        )
    trace.record("code", "get_recent_interactions", company_name, f"{len(bundle.items) - before} interaction(s)", started)

    budget.spend()
    started = time.monotonic()
    docs = await search_documents_tool("recent history, requests and open issues", company_name)
    before = len(bundle.items)
    for doc in docs.get("results", [])[:MAX_DOCS]:
        _add_item(bundle, f"document: {doc['title']}", doc["content"], f"document: {doc['title']}", scan=True)
    trace.record("tool", "search_documents", company_name, f"{len(bundle.items) - before} document chunk(s)", started)
    return bundle


def _evidence_for_agents(bundle: EvidenceBundle) -> str:
    return UNTRUSTED_CONTEXT_INSTRUCTION + "\n" + wrap_untrusted_context(bundle.text.strip())


def _response(status: str, trace: Trace, **extra) -> dict:
    return {"route": "agent", "status": status, "trace": trace.to_list(), **extra}


async def run_account_review(message: str, llm: agents.LlmCall, limits: AgentLimits | None = None) -> dict:
    limits = limits or AgentLimits.from_env()
    trace = Trace()
    try:
        async with asyncio.timeout(limits.timeout_seconds):
            return await _run(message, llm, limits, trace)
    except TimeoutError:
        return _response("timed_out", trace, message=f"Stopped after {limits.timeout_seconds:.0f}s.")
    except BudgetExceeded as exc:
        return _response("budget_exceeded", trace, message=str(exc))


async def _run(message: str, llm: agents.LlmCall, limits: AgentLimits, trace: Trace) -> dict:
    budget = RunBudget(limits)
    started = time.monotonic()
    question_finding = await guard_input(message)
    companies = await list_companies()
    company = find_mentioned_company(question_finding.neutralized_text, companies)
    trace.record(
        "code",
        "identify_company",
        message,
        company.name if company else "no company found",
        started,
        status="ok" if company else "error",
    )
    if company is None:
        return _response("company_not_found", trace, message="Name a company from the CRM to analyze.")

    bundle = await _gather_evidence(company.name, company.id, budget, trace)
    evidence_text = _evidence_for_agents(bundle)
    labels = {item["label"] for item in bundle.items}
    llm_calls: list[dict] = []

    def note_call(agent: str, result) -> None:
        llm_calls.append(
            {
                "agent": agent,
                "provider": result.provider,
                "model": result.model,
                "latencyMs": result.latency_ms,
                "fallbackUsed": result.fallback_used,
            }
        )

    feedback: list[str] | None = None
    revisions = 0
    while True:
        budget.spend()
        started = time.monotonic()
        recommendation, result = await agents.run_analyst(llm, evidence_text, feedback)
        note_call("analyst", result)
        trace.record(
            "agent",
            "Analyst agent" + (" (revision)" if revisions else ""),
            f"{len(bundle.items)} evidence item(s)",
            recommendation.action,
            started,
        )

        budget.spend()
        started = time.monotonic()
        review, result = await agents.run_reviewer(llm, evidence_text, recommendation)
        note_call("reviewer", result)
        unknown = agents.unknown_citations(recommendation, labels)
        if unknown:
            review = agents.Review("revise", [*review.reasons, f"Cited evidence that does not exist: {', '.join(unknown)}"])
        elif not recommendation.evidence:
            review = agents.Review("revise", [*review.reasons, "No evidence was cited."])
        trace.record("agent", "Reviewer agent", recommendation.action, f"{review.verdict}: {'; '.join(review.reasons)}", started)

        if review.verdict == "approve":
            break
        if revisions >= limits.max_revisions:
            break
        revisions += 1
        feedback = review.reasons

    approved = review.verdict == "approve"
    budget.spend()
    started = time.monotonic()
    task_note, result = await agents.run_task_drafter(llm, recommendation)
    note_call("task_drafter", result)
    trace.record("agent", "Task Drafter agent", recommendation.action, task_note, started)

    # Output guard: same cross-customer / leak scan the chat routes use
    names = [c.name for c in companies]
    action_finding = scan_output(recommendation.action, company.name, names)
    rationale_finding = scan_output(recommendation.rationale, company.name, names)
    note_finding = scan_output(task_note, company.name, names)
    report = build_report(
        (question_finding, "user_input"),
        *bundle.findings,
    )
    report = add_findings(
        report,
        (action_finding, "output: recommendation"),
        (rationale_finding, "output: rationale"),
        (note_finding, "output: task note"),
    )
    if report.flagged:
        logger.warning("prompt_guard_flagged agent %s", report.reasons)
        await record_events("agent", report.events)

    trace.record("gate", "awaiting_user_confirmation", "task not created", f"proposed: {note_finding.neutralized_text}", time.monotonic())
    return _response(
        "completed",
        trace,
        company={"id": company.id, "name": company.name},
        evidence=bundle.items,
        recommendation={
            "action": action_finding.neutralized_text,
            "rationale": rationale_finding.neutralized_text,
            "evidence": recommendation.evidence,
        },
        review={"approved": approved, "verdict": review.verdict, "reasons": review.reasons, "revisions": revisions},
        proposedTask={"companyName": company.name, "note": note_finding.neutralized_text},
        guardrail={"flagged": report.flagged, "reasons": report.reasons},
        llmCalls=llm_calls,
    )
