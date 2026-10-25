"""Stage 9 MCP tool implementations.

Each tool is a plain async function (no MCP-specific code here -- that
wiring lives in server.py) that wraps EXISTING crm/rag modules, per the
project's "tool functions must call existing CRM/RAG modules, must not
duplicate SQL or retrieval logic" rule. Every invocation (read or mutating)
is recorded in tool_audit_log for Stage 9's db-backed audit trail.
"""

import json

from app.chat.router import find_mentioned_company
from app.crm.queries import CompanyRef, get_company_summary, list_companies
from app.db import get_pool
from app.rag.retrieve import retrieve_relevant_chunks


async def _resolve_company(company_name: str) -> CompanyRef | None:
    """Resolves a (possibly partial/fuzzy) company name, as given by the LLM
    in a tool call, using the same substring-match heuristic already used
    for chat query-routing (app/chat/router.py) -- one company-matching
    behavior, not two."""
    companies = await list_companies()
    return find_mentioned_company(company_name, companies)


# Audit trail: every tool call is written to the tool_audit_log Postgres table
async def _log_tool_call(
    tool_name: str,
    arguments: dict,
    status: str,
    result_summary: str,
    company_id: int | None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO tool_audit_log (tool_name, arguments, status, result_summary, company_id)
           VALUES ($1, $2::jsonb, $3, $4, $5)""",
        tool_name,
        json.dumps(arguments),
        status,
        result_summary,
        company_id,
    )


async def get_company_summary_tool(company_name: str) -> dict:
    """Read tool: verified company facts (industry, relationship status, open
    deals, won/lost deal counts) -- same data as the CRM copilot's "facts"
    block, via the same app.crm.queries.get_company_summary function."""
    company = await _resolve_company(company_name)
    if company is None:
        result = {"status": "not_found", "message": f'No company matching "{company_name}" was found.'}
        await _log_tool_call("get_company_summary", {"company_name": company_name}, "error", result["message"], None)
        return result

    summary = await get_company_summary(company.id)
    result = {
        "status": "executed",
        "company": {
            "id": summary.id,
            "name": summary.name,
            "industry": summary.industry,
            "relationshipStatus": summary.relationship_status,
            "openDeals": [
                {"name": d.name, "amount": d.amount, "status": d.status, "expectedCloseDate": d.expected_close_date}
                for d in summary.open_deals
            ],
            "wonDealsCount": summary.won_deals_count,
            "lostDealsCount": summary.lost_deals_count,
        },
    }
    await _log_tool_call(
        "get_company_summary",
        {"company_name": company_name},
        "executed",
        f"Returned summary for {summary.name}",
        company.id,
    )
    return result


async def get_open_deals_tool(company_name: str) -> dict:
    """Read tool: a company's open deals only (narrower than the full
    summary), via app.crm.queries.get_company_summary."""
    company = await _resolve_company(company_name)
    if company is None:
        result = {"status": "not_found", "message": f'No company matching "{company_name}" was found.'}
        await _log_tool_call("get_open_deals", {"company_name": company_name}, "error", result["message"], None)
        return result

    summary = await get_company_summary(company.id)
    result = {
        "status": "executed",
        "companyName": summary.name,
        "openDeals": [
            {"name": d.name, "amount": d.amount, "status": d.status, "expectedCloseDate": d.expected_close_date}
            for d in summary.open_deals
        ],
    }
    await _log_tool_call(
        "get_open_deals",
        {"company_name": company_name},
        "executed",
        f"Returned {len(summary.open_deals)} open deal(s) for {summary.name}",
        company.id,
    )
    return result


async def search_documents_tool(query: str, company_name: str | None = None) -> dict:
    """Read tool: document knowledge search, via the same Stage 3/5 retrieval
    pipeline (app.rag.retrieve.retrieve_relevant_chunks) the RAG/CRM chat
    routes use. Results are untrusted document content -- the chat loop
    guardrail-scans and <untrusted_context>-wraps them before they reach the
    model, exactly like Stage 8's document handling."""
    company = await _resolve_company(company_name) if company_name else None
    chunks = await retrieve_relevant_chunks(query, company.id if company else None)
    result = {
        "status": "executed",
        "results": [
            {
                "title": chunk.document_title,
                "companyName": chunk.company_name,
                "docType": chunk.doc_type,
                "similarity": chunk.similarity,
                "content": chunk.content,
            }
            for chunk in chunks
        ],
    }
    await _log_tool_call(
        "search_documents",
        {"query": query, "company_name": company_name},
        "executed",
        f"Found {len(chunks)} document chunk(s)",
        company.id if company else None,
    )
    return result


_CONFIRMATION_WORDS = {"yes", "confirm", "confirmed", "approve", "approved", "go ahead", "do it", "proceed"}


def looks_like_confirmation(text: str) -> bool:
    """Stage 9's chosen confirmation UX: a mutating tool call only actually
    executes if the user's own latest message contains an explicit
    affirmative word/phrase -- deliberately simple/stateless rather than
    tracking a pending-proposal id across turns."""
    lower = text.strip().lower()
    return any(word in lower for word in _CONFIRMATION_WORDS)


async def create_followup_task_tool(company_name: str, note: str, confirm: bool = False) -> dict:
    """Mutating tool: proposes a follow-up task; only writes to the `tasks`
    table when `confirm` is true (set by the chat route based on
    looks_like_confirmation() against the user's latest message, never by
    the model itself deciding on its own to skip confirmation)."""
    company = await _resolve_company(company_name)
    if company is None:
        result = {"status": "not_found", "message": f'No company matching "{company_name}" was found.'}
        await _log_tool_call("create_followup_task", {"company_name": company_name, "note": note}, "error", result["message"], None)
        return result

    if not confirm:
        result = {
            "status": "proposed",
            "message": "Task not yet created -- ask the user to confirm before calling this tool again.",
            "proposedTask": {"companyName": company.name, "note": note},
        }
        await _log_tool_call(
            "create_followup_task",
            {"company_name": company_name, "note": note, "confirm": False},
            "proposed",
            f"Proposed task for {company.name}: {note}",
            company.id,
        )
        return result

    pool = await get_pool()
    row = await pool.fetchrow(
        "INSERT INTO tasks (company_id, note) VALUES ($1, $2) RETURNING id, status, created_at::text AS created_at",
        company.id,
        note,
    )
    result = {
        "status": "confirmed",
        "task": {"id": row["id"], "companyName": company.name, "note": note, "status": row["status"], "createdAt": row["created_at"]},
    }
    await _log_tool_call(
        "create_followup_task",
        {"company_name": company_name, "note": note, "confirm": True},
        "confirmed",
        f"Created task #{row['id']} for {company.name}",
        company.id,
    )
    return result
