"""POST /api/v1/agent/supervise (a Python-edition extension, E3.1 and E3.2, ADRs 0033 and 0034; not part of the
API contract shared with the Java edition): the same request as `/agent/recommend`, handled by a supervisor
that chooses the specialists turn by turn. An account follow-up gets the recommend shape plus a `supervisor`
object with every decision, and a completed run waits at the same approval gate: `POST /agent/confirm`
resumes it. Nothing is written before the user says yes. A plain question is handled by an answer team
instead and ends with an answer (no task, no gate).
"""

from fastapi import APIRouter, HTTPException

from app.agent.supervisor import run_supervised
from app.llm.gateway import LlmUnavailableError
from app.rag.embeddings import EmbeddingsUnavailableError
from app.routes.agent import RecommendRequest, make_llm

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/supervise")
async def supervise(body: RecommendRequest):
    try:
        return await run_supervised(body.message, make_llm(body.model))
    except (LlmUnavailableError, EmbeddingsUnavailableError) as exc:
        # no model or no embeddings key: say what to fix instead of an opaque 500
        raise HTTPException(status_code=503, detail=str(exc)) from exc
