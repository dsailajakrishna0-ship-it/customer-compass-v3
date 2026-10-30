"""Query-time retrieval: embed the question, find the closest chunks, and
shape them into citable sources for the LLM prompt and the UI.

Ported from apps/api/src/rag/retrieve.ts. Searches Qdrant instead of
Postgres/pgvector — each chunk's payload is already fully self-contained
(document title, source path, doc type, company name/id, content, char
offsets), so no join back to Postgres is needed here.
"""

import logging
import time
from dataclasses import dataclass
from typing import cast

from qdrant_client.models import (
    FieldCondition,
    Filter,
    IsNullCondition,
    MatchValue,
    PayloadField,
    SearchParams,
)

from app.config import get_settings
from app.rag.embeddings import embed_text
from app.rag.qdrant_store import collection_name, get_client

# Retrieval: embed the question, then ask Qdrant for the top-k most similar chunks
DEFAULT_TOP_K = 4
# Chunks below this cosine similarity are treated as not relevant enough to cite.
#
# Tuned empirically for gemini-embedding-001 (see evals/README.md, Stage 6):
# sampled questions against the live sample-data corpus showed genuinely
# relevant chunks scoring ~0.50-0.80, while clearly unrelated questions
# ("What is the capital of France?", "How do I bake a chocolate cake?")
# scored ~0.42-0.44. 0.45 sits in the gap between those two clusters. Note
# this does NOT fully solve plausible-but-uncovered questions (e.g. "What
# is our refund policy?" scores ~0.50-0.54, same range as real matches,
# because it's topically CRM/support-adjacent) — that's a known limitation
# of similarity-only filtering; the LLM's "not in the sources" response
# text is still the real safety net for those, and the eval suite checks
# for that behavior rather than expecting zero citations.
MIN_SIMILARITY = 0.45

# Stage 3.a scale-aware search: small collections are searched exactly (every
# vector compared, always correct); at or above `vector_index_min_points` the search
# switches to approximate HNSW with `vector_hnsw_ef` (how many candidates HNSW explores
# per query: higher = more accurate, slower). Qdrant does a similar switch internally;
# making it explicit here shows which path ran. The point count is cached for
# `vector_count_cache_seconds` so retrieval does not call Qdrant's count on every question.

logger = logging.getLogger("app.rag.retrieve")

_count_cache: tuple[float, int] | None = None


def choose_search_strategy(point_count: int) -> tuple[str, SearchParams]:
    """Pure decision: ("exact", ...) below the threshold, ("hnsw", ...) at or above it."""
    settings = get_settings()
    if point_count < settings.vector_index_min_points:
        return "exact", SearchParams(exact=True)
    return "hnsw", SearchParams(hnsw_ef=settings.vector_hnsw_ef)


async def get_point_count() -> int:
    """Number of points in the collection, cached for `vector_count_cache_seconds`."""
    global _count_cache
    now = time.monotonic()
    if (
        _count_cache is not None
        and now - _count_cache[0] < get_settings().vector_count_cache_seconds
    ):
        return _count_cache[1]
    result = await get_client().count(collection_name=collection_name(), exact=False)
    _count_cache = (now, result.count)
    return result.count


def reset_count_cache() -> None:
    global _count_cache
    _count_cache = None


@dataclass
class RetrievedChunk:
    chunk_id: int | str
    document_id: int
    document_title: str
    source_path: str
    doc_type: str
    company_name: str | None
    chunk_index: int
    content: str
    similarity: float


def _company_filter(company_id: int | None) -> Filter | None:
    if company_id is None:
        return None
    # Another customer's material is never retrieved for a scoped question:
    # only this company's documents and company-agnostic documents (e.g.
    # product overviews, company_id IS NULL) are eligible.
    return Filter(
        should=[
            FieldCondition(key="company_id", match=MatchValue(value=company_id)),
            IsNullCondition(is_null=PayloadField(key="company_id")),
        ]
    )


async def retrieve_relevant_chunks(
    question: str,
    company_id: int | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Finds the closest document chunks to `question`. When `company_id` is
    given (company-scoped question), only that company's documents and
    company-agnostic documents are eligible."""
    query_embedding = await embed_text(question)
    client = get_client()
    strategy, search_params = choose_search_strategy(await get_point_count())
    logger.info("vector_search strategy=%s collection=%s", strategy, collection_name())

    results = await client.query_points(
        collection_name=collection_name(),
        query=query_embedding,
        query_filter=_company_filter(company_id),
        search_params=search_params,
        limit=top_k,
        with_payload=True,
    )

    chunks = []
    for point in results.points:
        if point.score < MIN_SIMILARITY:
            continue
        payload = point.payload or {}
        chunks.append(
            RetrievedChunk(
                chunk_id=cast(int | str, point.id),
                document_id=payload["document_id"],
                document_title=payload["document_title"],
                source_path=payload["source_path"],
                doc_type=payload["doc_type"],
                company_name=payload.get("company_name"),
                chunk_index=payload["chunk_index"],
                content=payload["content"],
                similarity=point.score,
            )
        )
    return chunks


def build_context(chunks: list[RetrievedChunk]) -> str:
    """Builds the numbered, citable context block injected into the LLM prompt."""
    return "\n\n".join(
        f"[{i + 1}] Source: {chunk.document_title} ({chunk.doc_type})\n{chunk.content}"
        for i, chunk in enumerate(chunks)
    )
