"""Stage 10 endpoints for the Account Follow-up Recommender.

POST /agent/recommend runs the bounded workflow and returns the evidence,
recommendation, review verdict, proposed task and the full trace. It never
writes. POST /agent/confirm is the only place a task can be created, and only
when the user explicitly sends confirm=true (declining writes nothing).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.agents import AgentRole, LlmCall
from app.agent.policies import needs_agent
from app.agent.workflow import run_account_review
from app.guardrails.audit import record_events
from app.guardrails.prompt_guard import build_report, scan_and_neutralize
from app.llm.gateway import LlmUnavailableError, generate
from app.llm.types import ChatMessage
from app.mcp.tools import create_followup_task_tool
from app.rag.embeddings import EmbeddingsUnavailableError

router = APIRouter(prefix="/agent", tags=["agent"])


class RecommendRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    model: str | None = None


class ConfirmRequest(BaseModel):
    company_name: str = Field(..., alias="companyName", min_length=1, max_length=200)
    note: str = Field(..., min_length=1, max_length=300)
    confirm: bool

    model_config = {"populate_by_name": True}


def make_llm(model: str | None) -> LlmCall:
    """The model call the agents use: `llm(role, system_prompt, messages)` through the gateway.

    This is the one place the agent API meets the model, and one of the two documented seams of the
    contract tests (tests/README.md): they replace it with a fake that answers by role."""

    async def llm(_role: AgentRole, system_prompt: str, messages: list[ChatMessage]):
        return await generate(system_prompt, messages, model)

    return llm


# Agent route: only analysis requests run the multi-step workflow; simple questions are sent back to the direct chat modes
@router.post("/recommend")
async def recommend(body: RecommendRequest):
    if not needs_agent(body.message):
        return {
            "route": "direct",
            "message": "This looks like a simple question. Use the CRM copilot or document chat mode instead of the agent.",
        }

    try:
        return await run_account_review(body.message, make_llm(body.model))
    except (LlmUnavailableError, EmbeddingsUnavailableError) as exc:
        # no model or no embeddings key: say what to fix instead of an opaque 500
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# Human approval: the only step that can create a task
@router.post("/confirm")
async def confirm(body: ConfirmRequest):
    finding = scan_and_neutralize(body.note)
    if finding.matched_patterns:
        await record_events("agent", build_report((finding, "user_input: task note")).events)
    if not body.confirm:
        return {"status": "declined", "message": "No task was created."}

    result = await create_followup_task_tool(
        body.company_name, finding.neutralized_text, confirm=True
    )
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result["message"])
    return result
