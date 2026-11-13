"""Qdrant vector store client for document chunks.

Replaces Postgres/pgvector's document_chunks table (used by the Express API)
for the v2 stack migration. Each chunk is stored as a Qdrant point whose
payload is fully self-contained (document title, source path, doc type,
company name/id, chunk text, char offsets) so query-time retrieval never
needs a join back to Postgres just to cite a source.

Postgres still holds the `documents` and `ingestion_runs` tables as the
system of record for ingestion metadata/history; Qdrant only holds chunk
vectors + their citable payload.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    Modifier,
    PointStruct,
    SparseVectorParams,
    VectorParams,
)

from app.config import get_settings
from app.rag.embeddings import embedding_dimensions, embedding_model_id

# Vector DB: Qdrant stores chunk embeddings and does nearest-neighbour search

# Every chunk point holds two named vectors (Stage 4.1): "dense" is the meaning embedding,
# "bm25" is the keyword vector built in app/rag/sparse.py.
DENSE = "dense"
SPARSE = "bm25"


# Which collection the code in this task is working on. Normally unset: the configured collection (the
# CRM documents). A knowledge base (app/rag/knowledge_bases.py, ADR 0029) sets it for the duration of
# one ingestion or search, so the same retrieval code serves every corpus without a collection
# argument on every function. A ContextVar is per asyncio task, so two concurrent requests for two
# knowledge bases never see each other's value.
_collection_override: ContextVar[str | None] = ContextVar(
    "qdrant_collection_override", default=None
)
_ingest_hint: ContextVar[str | None] = ContextVar("qdrant_ingest_hint", default=None)


def collection_name() -> str:
    return _collection_override.get() or get_settings().qdrant_collection


def ingest_hint() -> str:
    """What to tell a person whose index was built with another embedding model."""
    return _ingest_hint.get() or "Click Ingest documents (or POST /api/v1/documents/ingest)"


@contextmanager
def using_collection(name: str, hint: str | None = None) -> Iterator[None]:
    """Everything inside the block (including awaits) uses collection `name` instead of the configured one."""
    token, hint_token = _collection_override.set(name), _ingest_hint.set(hint)
    try:
        yield
    finally:
        _collection_override.reset(token)
        _ingest_hint.reset(hint_token)


_client: AsyncQdrantClient | None = None


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=get_settings().qdrant_url)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def recreate_collection() -> None:
    """Drops and recreates the collection so re-ingestion never duplicates
    or leaves stale points behind (mirrors the Express pipeline's
    `TRUNCATE document_chunks` behavior)."""
    client = get_client()
    if await client.collection_exists(collection_name()):
        await client.delete_collection(collection_name())
    await client.create_collection(
        collection_name=collection_name(),
        # Cosine distance: compares vector direction, so similar meaning scores close to 1
        vectors_config={DENSE: VectorParams(size=embedding_dimensions(), distance=Distance.COSINE)},
        # IDF modifier: Qdrant multiplies each word's weight by how rare the word is across all
        # chunks, which together with the term weights from sparse.py gives BM25 scoring
        sparse_vectors_config={SPARSE: SparseVectorParams(modifier=Modifier.IDF)},
        # which embedding model made the vectors: a changed model is noticed at search time (4.3)
        metadata={"embedding_model": embedding_model_id()},
    )


async def index_embedding_model() -> str | None:
    """The embedding model recorded when the collection was created, or None if it records none."""
    info = await get_client().get_collection(collection_name())
    metadata = info.config.metadata or {}
    model = metadata.get("embedding_model")
    return model if isinstance(model, str) else None


async def upsert_chunks(points: list[PointStruct]) -> None:
    if len(points) == 0:
        return
    client = get_client()
    await client.upsert(collection_name=collection_name(), points=points)


async def count_chunks(document_id: int | None = None) -> int:
    client = get_client()
    query_filter: Filter | None = None
    if document_id is not None:
        query_filter = Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        )
    result = await client.count(
        collection_name=collection_name(), count_filter=query_filter, exact=True
    )
    return result.count
