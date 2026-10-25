"""FastAPI service for the v2 stack migration (Stage 6 prep, PR 5 of N).

This service replaces the Express API (apps/api) for the frontend. PR 2
proved the FastAPI + uv + Docker wiring works end to end (health check
against Postgres). PR 3 added document ingestion into Qdrant. PR 4 added
the chat/RAG query routes (general chat, grounded RAG, CRM copilot) and
the OpenRouter model list. PR 5 adds the company list/detail routes and
cuts the frontend over to this service — all frontend-facing routes live
under /api/v1 (matching the old Express API's /api prefix, with a version
segment added since this is now the long-term API surface). /health stays
unprefixed, same as it was in Express.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.db import close_pool, get_pool
from app.guardrails.audit import ensure_schema_and_purge
from app.rag.qdrant_store import close_client
from app.routes.agent import router as agent_router
from app.routes.chat import router as chat_router
from app.routes.companies import router as companies_router
from app.routes.documents import router as documents_router
from app.routes.llm import router as llm_router
from app.routes.security import router as security_router
from app.routes.tasks import router as tasks_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await ensure_schema_and_purge()
    yield
    await close_pool()
    await close_client()


# Backend: FastAPI is the Python web framework serving every /api/v1 route the React UI calls
app = FastAPI(title="Customer Compass API (Python)", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    """FastAPI's default HTTPException body is {"detail": ...}, but the
    frontend's ChatResponse/error-handling contract (ported from the old
    Express API) expects {"error": ...}. Without this, every backend error
    (e.g. an OpenRouter free-model rate-limit, which already has a helpful
    message) silently fell through to a generic "Something went wrong." in
    the UI, because `body.error` was always undefined. Returning both keys
    keeps FastAPI's default shape available while restoring the field the
    frontend actually reads."""
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail, "detail": exc.detail})

# CORS: lets the Vite dev UI (localhost:5173) call this API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(llm_router, prefix="/api/v1")
app.include_router(companies_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(security_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    """Mirrors apps/api's GET /health: confirms the API process is up *and*
    can reach Postgres, not just that the process is alive."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - surfaced as a clear 503 below
        raise HTTPException(status_code=503, detail=f"Database unreachable: {exc}") from exc
    return {"status": "ok"}
