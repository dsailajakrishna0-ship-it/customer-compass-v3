"""Query-time retrieval: embed the question, find the closest chunks, and
shape them into citable sources for the LLM prompt and the UI.

Ported from apps/api/src/rag/retrieve.ts. Searches Qdrant instead of
Postgres/pgvector — each chunk's payload is already fully self-contained
(document title, source path, doc type, company name/id, content, char
offsets), so no join back to Postgres is needed here.
"""

import logging
import math
import time
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import cast

from qdrant_client.models import (
    FieldCondition,
    Filter,
    IsNullCondition,
    MatchValue,
    PayloadField,
    ScoredPoint,
    SearchParams,
)

from app import tracing
from app.config import get_settings
from app.rag.embeddings import EmbeddingsUnavailableError, embed_text, embedding_model_id
from app.rag.qdrant_store import (
    DENSE,
    SPARSE,
    collection_name,
    get_client,
    index_embedding_model,
)
from app.rag.rerank import rerank_order, reranking_enabled
from app.rag.sparse import query_vector

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


class EmbeddingModelMismatchError(EmbeddingsUnavailableError):
    """The documents were embedded with a different model from the one now configured."""


_index_model_checked: tuple[float, str] | None = None


async def check_index_model() -> None:
    """Stops a search whose question would be embedded with a different model from the documents.

    Vectors from two models are not comparable (they can even have different lengths), so searching
    one with the other returns nonsense or an error. The model that built the index is recorded on
    the collection; if it is not the configured one, the fix is one re-ingest. An index that records
    no model (made before 4.3) is not checked. The result is cached for `vector_count_cache_seconds`."""
    global _index_model_checked
    current = embedding_model_id()
    now = time.monotonic()
    ttl = get_settings().vector_count_cache_seconds
    if (
        _index_model_checked
        and _index_model_checked[1] == current
        and now - _index_model_checked[0] < ttl
    ):
        return
    indexed = await index_embedding_model()
    if indexed is not None and indexed != current:
        raise EmbeddingModelMismatchError(
            f"The documents were embedded with {indexed}, but the embedding model is now {current}. "
            "Click Ingest documents (or POST /api/v1/documents/ingest) to re-embed them."
        )
    _index_model_checked = (now, current)


def reset_index_model_check() -> None:
    global _index_model_checked
    _index_model_checked = None


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
    page: int | None = None  # PDF page the chunk is on (Stage 4.2)
    sheet: str | None = None  # spreadsheet sheet it is from (Stage 4.2)

    @property
    def location(self) -> str:
        """Where in the file the chunk is, for a citation: "page 3", "sheet Deals", or nothing."""
        if self.page is not None:
            return f"page {self.page}"
        if self.sheet is not None:
            return f"sheet {self.sheet}"
        return ""


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


def rrf_fuse[T: Hashable](rankings: Sequence[Sequence[T]], k: int = 60) -> list[T]:
    """Reciprocal rank fusion: merges several best-first rankings into one.

    Each item scores `1 / (k + rank)` in every ranking that contains it (rank starts at 1), and the
    scores add up. An item both searches like beats an item only one of them found. Only positions
    are used, never the raw scores, so a cosine score and a BM25 score (which are on different
    scales) can be merged without any tuning. A larger `k` makes the blend flatter."""
    scores: dict[T, float] = {}
    for ranking in rankings:
        for position, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1 / (k + position)
    return sorted(scores, key=lambda item: scores[item], reverse=True)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two dense vectors (what Qdrant's own score is for the dense vector)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


async def _dense_points(
    question_embedding: list[float], company_id: int | None, limit: int
) -> list[ScoredPoint]:
    strategy, search_params = choose_search_strategy(await get_point_count())
    logger.info("vector_search strategy=%s collection=%s", strategy, collection_name())
    result = await get_client().query_points(
        collection_name=collection_name(),
        query=question_embedding,
        using=DENSE,
        query_filter=_company_filter(company_id),
        search_params=search_params,
        limit=limit,
        with_payload=True,
    )
    return result.points


async def _keyword_points(question: str, company_id: int | None, limit: int) -> list[ScoredPoint]:
    """Chunks that share the question's exact words, best first (BM25). The dense vector is returned
    too, so a chunk found only by keywords can still get a meaning-similarity score."""
    sparse = query_vector(question)
    if not sparse.indices:
        return []
    result = await get_client().query_points(
        collection_name=collection_name(),
        query=sparse,
        using=SPARSE,
        query_filter=_company_filter(company_id),
        limit=limit,
        with_payload=True,
        with_vectors=[DENSE],
    )
    return result.points


def _chunk(point: ScoredPoint, similarity: float) -> RetrievedChunk:
    payload = point.payload or {}
    return RetrievedChunk(
        chunk_id=cast(int | str, point.id),
        document_id=payload["document_id"],
        document_title=payload["document_title"],
        source_path=payload["source_path"],
        doc_type=payload["doc_type"],
        company_name=payload.get("company_name"),
        chunk_index=payload["chunk_index"],
        content=payload["content"],
        similarity=similarity,
        page=payload.get("page"),
        sheet=payload.get("sheet"),
    )


async def retrieve_relevant_chunks(
    question: str,
    company_id: int | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """One retrieval, as one span (Stage 5.1): the mode, how many chunks came back and how similar the
    best and the weakest were. Never the question or the chunk text (unless content capture is on)."""
    with tracing.span("retrieval", "retriever") as span:
        chunks = await _retrieve_relevant_chunks(question, company_id, top_k)
        if tracing.tracing_active():
            span.set(
                {
                    "retrieval.mode": get_settings().retrieval_mode,
                    "retrieval.top_k": top_k,
                    "retrieval.company_scoped": company_id is not None,
                    "retrieval.reranker": get_settings().rerank_provider,
                    "retrieval.query_chars": len(question),
                    "retrieval.results": len(chunks),
                    "retrieval.similarity_max": max((c.similarity for c in chunks), default=None),
                    "retrieval.similarity_min": min((c.similarity for c in chunks), default=None),
                    "langfuse.observation.input": question if tracing.capture_content() else None,
                }
            )
        return chunks


async def _retrieve_relevant_chunks(
    question: str,
    company_id: int | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Finds the best document chunks for `question`. When `company_id` is given (company-scoped
    question), only that company's documents and company-agnostic documents are eligible.

    `retrieval_mode` decides how (Stage 4.1): "dense" asks Qdrant for the closest meanings;
    "hybrid" also asks for the chunks sharing the question's exact words and merges the two
    rankings with reciprocal rank fusion. In both modes a chunk whose meaning-similarity is
    below MIN_SIMILARITY is dropped, so an unrelated question still finds nothing to cite.

    Stage 4.1b: when a reranker is configured (`RERANK_PROVIDER`), the best `retrieval_candidates`
    chunks are sent to it and its order decides the final `top_k`; if it fails, the search order stays."""
    settings = get_settings()
    await check_index_model()
    # With a reranker we keep a longer shortlist for it to choose from; without one, just top_k
    pool = settings.retrieval_candidates if reranking_enabled() else top_k

    if settings.retrieval_impl == "frameworks":
        # the LangChain side embeds the question itself, through our embedding function (ADR 0027)
        from app.frameworks.retriever import dense_chunks

        shortlist = (await dense_chunks(question, company_id, max(pool, top_k)))[:pool]
        return await _rerank(question, shortlist, top_k)

    question_embedding = await embed_text(question)
    if settings.retrieval_mode == "dense":
        points = await _dense_points(question_embedding, company_id, max(pool, top_k))
        shortlist = [_chunk(p, p.score) for p in points if p.score >= MIN_SIMILARITY][:pool]
        return await _rerank(question, shortlist, top_k)

    limit = settings.retrieval_candidates
    dense = await _dense_points(question_embedding, company_id, limit)
    keyword = await _keyword_points(question, company_id, limit)
    similarity = {p.id: p.score for p in dense}
    points_by_id = {p.id: p for p in [*keyword, *dense]}
    for point in keyword:
        if point.id not in similarity:
            vector = point.vector.get(DENSE) if isinstance(point.vector, dict) else None
            similarity[point.id] = (
                cosine(question_embedding, cast(list[float], vector)) if vector else 0.0
            )
    order = rrf_fuse([[p.id for p in dense], [p.id for p in keyword]], settings.rrf_k)
    logger.info("hybrid_search dense=%d keyword=%d merged=%d", len(dense), len(keyword), len(order))
    kept = [i for i in order if similarity[i] >= MIN_SIMILARITY][:pool]
    return await _rerank(question, [_chunk(points_by_id[i], similarity[i]) for i in kept], top_k)


async def _rerank(
    question: str, shortlist: list[RetrievedChunk], top_k: int
) -> list[RetrievedChunk]:
    """Re-orders the shortlist with the reranker when one is configured and answers; otherwise the
    first `top_k` in the order the search gave them. Never raises because of the reranker."""
    if not reranking_enabled() or len(shortlist) <= 1:
        return shortlist[:top_k]
    texts = [f"{chunk.document_title}: {chunk.content}" for chunk in shortlist]
    order = await rerank_order(question, texts, top_k)
    if order is None:
        return shortlist[:top_k]
    logger.info("reranked candidates=%d kept=%d", len(shortlist), len(order))
    return [shortlist[i] for i in order]


def build_context(chunks: list[RetrievedChunk]) -> str:
    """Builds the numbered, citable context block injected into the LLM prompt."""
    return "\n\n".join(
        f"[{i + 1}] Source: {chunk.document_title} "
        f"({chunk.doc_type}{', ' + chunk.location if chunk.location else ''})\n{chunk.content}"
        for i, chunk in enumerate(chunks)
    )
