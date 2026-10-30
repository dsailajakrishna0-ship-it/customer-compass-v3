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

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import get_settings
from app.rag.embeddings import EMBEDDING_DIMENSIONS

# Vector DB: Qdrant stores chunk embeddings and does nearest-neighbour search


def collection_name() -> str:
    return get_settings().qdrant_collection


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
        vectors_config=VectorParams(size=EMBEDDING_DIMENSIONS, distance=Distance.COSINE),
    )


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
