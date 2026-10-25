"""Document ingestion + inspection routes (ported from apps/api/src/routes/documents.ts)."""

from fastapi import APIRouter, HTTPException

from app.db import get_pool
from app.rag.ingest import ingest_documents
from app.rag.qdrant_store import COLLECTION_NAME, count_chunks
from app.rag.retrieve import (
    VECTOR_HNSW_EF,
    VECTOR_INDEX_MIN_POINTS,
    choose_search_strategy,
    get_point_count,
)

router = APIRouter(prefix="/documents", tags=["documents"])


# Stage 3.a: shows which search path retrieval will use for the current collection size
@router.get("/vector-search-info")
async def vector_search_info():
    points = await get_point_count()
    strategy, _ = choose_search_strategy(points)
    return {
        "collection": COLLECTION_NAME,
        "points": points,
        "strategy": strategy,
        "minPointsForHnsw": VECTOR_INDEX_MIN_POINTS,
        "hnswEf": VECTOR_HNSW_EF,
    }


# Ingestion: chunks sample docs, embeds them (Google) and stores vectors in Qdrant, metadata in Postgres
@router.post("/ingest")
async def ingest():
    """Runs the full parse -> chunk -> embed -> store pipeline over sample-data/documents."""
    try:
        summary = await ingest_documents()
    except Exception as exc:  # noqa: BLE001 - mirrors the Express route's catch-all 500
        raise HTTPException(status_code=500, detail="Ingestion failed. Check the API logs.") from exc

    status_code = 200 if summary.status == "completed" else 502
    body = {
        "ingestionRunId": summary.ingestion_run_id,
        "documentsProcessed": summary.documents_processed,
        "chunksCreated": summary.chunks_created,
        "status": summary.status,
    }
    if summary.error:
        body["error"] = summary.error
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=body)
    return body


@router.get("")
async def list_documents():
    """Lists ingested documents with their chunk counts, for debugging retrieval."""
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT d.id, d.title, d.doc_type, d.source_path, c.name AS company_name
           FROM documents d
           LEFT JOIN companies c ON c.id = d.company_id
           ORDER BY d.id"""
    )
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "docType": row["doc_type"],
            "sourcePath": row["source_path"],
            "companyName": row["company_name"],
            "chunkCount": await count_chunks(document_id=row["id"]),
        }
        for row in rows
    ]


@router.get("/ingestion-runs")
async def list_ingestion_runs():
    """Returns the most recent ingestion runs, most recent first."""
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, started_at, completed_at, status, embedding_model, documents_processed, chunks_created, error
           FROM ingestion_runs
           ORDER BY started_at DESC
           LIMIT 10"""
    )
    return [
        {
            "id": row["id"],
            "startedAt": row["started_at"].isoformat() if row["started_at"] else None,
            "completedAt": row["completed_at"].isoformat() if row["completed_at"] else None,
            "status": row["status"],
            "embeddingModel": row["embedding_model"],
            "documentsProcessed": row["documents_processed"],
            "chunksCreated": row["chunks_created"],
            "error": row["error"],
        }
        for row in rows
    ]
