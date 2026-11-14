"""POST /api/v1/agent/supervise (a Python-edition extension, E3.1, ADR 0033; not part of the API contract
shared with the Java edition): the same request as `/agent/recommend`, handled by a supervisor that chooses
the specialists turn by turn. The answer has the recommend shape plus a `supervisor` object with every
decision, and a completed run waits at the same approval gate: `POST /agent/confirm` resumes it. Nothing is
written before the user says yes.
"""

from fastapi import APIRouter, HTTPException

from app.agent.policies import needs_agent
from app.agent.supervisor import run_supervised
from app.llm.gateway import LlmUnavailableError
from app.rag.embeddings import EmbeddingsUnavailableError
from app.routes.agent import RecommendRequest, make_llm

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/supervise")
async def supervise(body: RecommendRequest):
    if not needs_agent(body.message):
        return {
            "route": "direct",
            "message": "This looks like a simple question. Use the CRM copilot or document chat mode instead of the agent.",
        }
    try:
        return await run_supervised(body.message, make_llm(body.model))
    except (LlmUnavailableError, EmbeddingsUnavailableError) as exc:
        # no model or no embeddings key: say what to fix instead of an opaque 500
        raise HTTPException(status_code=503, detail=str(exc)) from exc
