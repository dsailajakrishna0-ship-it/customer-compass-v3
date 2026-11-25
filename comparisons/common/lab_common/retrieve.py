"""What every RAG-retrieval approach implements, and the HTTP face they share.

Retrieval embeds the question, asks the vector store for the closest chunks of the approach's own
ingestion collection and keeps the ones similar enough to cite. The face is
`POST /api/v1/retrieve` with `{"query": "...", "topK": 4, "minSimilarity": 0.6}` (only the query is
required) and `GET /health`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .chat import UnavailableError

DEFAULT_MIN_SIMILARITY = (
    0.60  # the application's calibrated value for gemini-embedding-001 (ADR 0024)
)
DEFAULT_TOP_K = 4
MAX_TOP_K = 20
MAX_QUERY_CHARACTERS = 1_000


@dataclass(frozen=True)
class Hit:
    """One chunk that was kept: its cosine similarity and where it came from."""

    score: float
    title: str | None
    source: str | None
    company: str | None
    chunk_index: int | None
    text: str


@dataclass(frozen=True)
class RetrieveResult:
    """`considered` is how many chunks the store returned (at most topK), `hits` the ones at or
    above the floor."""

    collection: str
    min_similarity: float
    considered: int
    hits: list[Hit] = field(default_factory=list)
    embedding_requests: int = 0
    embedding_model: str = ""
    latency_ms: int = 0


class Retrieve(Protocol):
    approach: str

    def search(self, query: str, top_k: int, min_similarity: float) -> RetrieveResult:
        """`top_k` and `min_similarity` are already validated."""
        ...


def parse_request(raw: bytes) -> tuple[str, int, float]:
    """query: a non-blank string of at most 1,000 characters. topK: an integer from 1 to 20
    (default 4). minSimilarity: a number from 0 to 1 (default 0.60). Raises ValueError with a
    message for the client."""
    if not raw.strip():
        raise ValueError("The body must be a JSON object with a query.")
    body = json.loads(raw.decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("The body must be a JSON object.")
    query = body.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query is required and must be a non-blank string.")
    if len(query) > MAX_QUERY_CHARACTERS:
        raise ValueError(f"query is limited to {MAX_QUERY_CHARACTERS} characters.")
    top_k: Any = body.get("topK")
    if top_k is None:
        top_k = DEFAULT_TOP_K
    elif isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"topK must be an integer from 1 to {MAX_TOP_K}.")
    floor: Any = body.get("minSimilarity")
    if floor is None:
        floor = DEFAULT_MIN_SIMILARITY
    elif isinstance(floor, bool) or not isinstance(floor, int | float) or not 0 <= floor <= 1:
        raise ValueError("minSimilarity must be a number from 0 to 1.")
    return query.strip(), int(top_k), float(floor)


def create_retrieve_app(retrieve: Retrieve) -> FastAPI:
    app = FastAPI(title=f"Retrieval backend: {retrieve.approach}", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "approach": retrieve.approach}

    @app.post("/api/v1/retrieve")
    async def search(request: Request) -> JSONResponse:
        try:
            query, top_k, floor = parse_request(await request.body())
        except (ValueError, UnicodeDecodeError) as exc:
            known = ("The body must", "query ", "topK ", "minSimilarity ")
            detail = str(exc) if str(exc).startswith(known) else "The body is not valid JSON."
            return JSONResponse({"detail": detail}, status_code=422)
        try:
            result = await run_in_threadpool(retrieve.search, query, top_k, floor)
        except UnavailableError as exc:
            return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=503)
        except Exception:  # noqa: BLE001 - never the exception's own text: it can carry a URL
            message = "Could not search."
            return JSONResponse({"error": message, "detail": message}, status_code=503)
        return JSONResponse(
            {
                "approach": retrieve.approach,
                "collection": result.collection,
                "minSimilarity": result.min_similarity,
                "considered": result.considered,
                "kept": len(result.hits),
                "hits": [
                    {
                        "score": hit.score,
                        "title": hit.title,
                        "source": hit.source,
                        "company": hit.company,
                        "chunkIndex": hit.chunk_index,
                        "text": hit.text,
                    }
                    for hit in result.hits
                ],
                "embeddingRequests": result.embedding_requests,
                "embeddingModel": result.embedding_model,
                "latencyMs": result.latency_ms,
            }
        )

    return app
