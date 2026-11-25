"""What every RAG-ingestion approach implements, and the HTTP face they share.

Ingestion is Read, Chunk, Embed, Store over a folder of documents, into a vector collection of the
approach's own. The face is `POST /api/v1/ingest` (the body is optional, or `{"limit": 3}`) and
`GET /health`. The source folder and the collection are fixed by the backend, never taken from the
request, so a caller cannot make it read another folder or write another collection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .chat import UnavailableError

MAX_LIMIT = 1_000


@dataclass(frozen=True)
class IngestResult:
    """What one run did. `embedding_requests` counts calls to the embedding service."""

    collection: str
    documents: int
    chunks: int
    embedding_requests: int
    embedding_model: str
    dimensions: int
    latency_ms: int


class Ingest(Protocol):
    approach: str

    def run(self, limit: int | None) -> IngestResult:
        """Runs the whole pipeline. The collection is replaced, so running twice never duplicates.
        `limit` (None for no limit) keeps only the first documents, in file name order: a way to
        try a run without spending much embedding quota."""
        ...


def parse_limit(raw: bytes) -> int | None:
    """An empty body or `{}` means no limit; otherwise `limit` is an integer from 1 to 1,000."""
    if not raw.strip():
        return None
    body = json.loads(raw.decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("The body must be a JSON object.")
    limit = body.get("limit")
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {MAX_LIMIT}.")
    return limit


def create_ingest_app(ingest: Ingest) -> FastAPI:
    app = FastAPI(title=f"Ingestion backend: {ingest.approach}", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "approach": ingest.approach}

    @app.post("/api/v1/ingest")
    async def run(request: Request) -> JSONResponse:
        try:
            limit = parse_limit(await request.body())
        except (ValueError, UnicodeDecodeError) as exc:
            detail = (
                str(exc)
                if str(exc).startswith(("limit", "The body must"))
                else "The body is not valid JSON."
            )
            return JSONResponse({"detail": detail}, status_code=422)
        try:
            result = await run_in_threadpool(ingest.run, limit)
        except UnavailableError as exc:
            return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=503)
        except Exception:  # noqa: BLE001 - never the exception's own text: it can carry a URL
            message = "Could not ingest."
            return JSONResponse({"error": message, "detail": message}, status_code=503)
        return JSONResponse(
            {
                "approach": ingest.approach,
                "status": "completed",
                "collection": result.collection,
                "documents": result.documents,
                "chunks": result.chunks,
                "embeddingRequests": result.embedding_requests,
                "embeddingModel": result.embedding_model,
                "dimensions": result.dimensions,
                "latencyMs": result.latency_ms,
            }
        )

    return app
