"""Stage 10 endpoints for the Account Follow-up Recommender.

POST /agent/recommend runs the bounded workflow and returns the evidence,
recommendation, review verdict, proposed task and the full trace. It never
writes. POST /agent/confirm is the only place a task can be created, and only
when the user explicitly sends confirm=true (declining writes nothing).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.policies import needs_agent
from app.agent.workflow import run_account_review
from app.guardrails.audit import record_events
from app.guardrails.prompt_guard import build_report, scan_and_neutralize
from app.llm.provider import LlmProvider, generate
from app.mcp.tools import create_followup_task_tool

router = APIRouter(prefix="/agent", tags=["agent"])


class RecommendRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    provider: LlmProvider | None = None
    model: str | None = None


class ConfirmRequest(BaseModel):
    company_name: str = Field(..., alias="companyName", min_length=1, max_length=200)
    note: str = Field(..., min_length=1, max_length=300)
    confirm: bool

    model_config = {"populate_by_name": True}


# Agent route: only analysis requests run the multi-step workflow; simple questions are sent back to the direct chat modes
@router.post("/recommend")
async def recommend(body: RecommendRequest):
    if not needs_agent(body.message):
        return {
            "route": "direct",
            "message": "This looks like a simple question. Use the CRM copilot or document chat mode instead of the agent.",
        }

    async def llm(system_prompt, messages):
        return await generate(system_prompt, messages, body.provider, body.model)

    return await run_account_review(body.message, llm)


# Human approval: the only step that can create a task
@router.post("/confirm")
async def confirm(body: ConfirmRequest):
    finding = scan_and_neutralize(body.note)
    if finding.matched_patterns:
        await record_events("agent", build_report((finding, "user_input: task note")).events)
    if not body.confirm:
        return {"status": "declined", "message": "No task was created."}

    result = await create_followup_task_tool(body.company_name, finding.neutralized_text, confirm=True)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result["message"])
    return result
