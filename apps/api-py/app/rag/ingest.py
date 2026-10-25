"""Document ingestion pipeline: parse -> chunk -> embed -> store.

Ported from apps/api/src/rag/ingest.ts for the v2 stack migration. Key
difference from the Express version: chunk text + embeddings are stored in
Qdrant (not Postgres/pgvector). Postgres keeps the `documents` and
`ingestion_runs` tables as the system of record for ingestion metadata/
history only.

This is intentionally a standalone, re-runnable process rather than
something that happens implicitly on every chat request. Ingestion is a
distinct lifecycle step from query-time retrieval.
"""

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import frontmatter
from qdrant_client.models import PointStruct

from app.db import get_pool
from app.rag.chunking import chunk_text
from app.rag.embeddings import EMBEDDING_MODEL, embed_texts
from app.rag.qdrant_store import recreate_collection, upsert_chunks

DOCUMENT_TYPES = {"email", "call", "note", "support", "product"}


@dataclass
class ParsedDocument:
    source_path: str
    title: str
    doc_type: str
    company_name: str | None
    content: str


@dataclass
class IngestSummary:
    ingestion_run_id: int
    documents_processed: int
    chunks_created: int
    status: str
    error: str | None = None


def _documents_dir() -> Path:
    override = os.environ.get("SAMPLE_DATA_DIR")
    if override:
        return Path(override)
    # Local dev default: apps/api-py/app/rag/ingest.py -> repo root -> sample-data/documents.
    # In Docker, SAMPLE_DATA_DIR is set explicitly (see docker-compose.yml) because the
    # container image only contains apps/api-py, not the whole repo.
    here = Path(__file__).resolve()
    return here.parents[4] / "sample-data" / "documents"


def _load_documents() -> list[ParsedDocument]:
    dir_path = _documents_dir()
    repo_root = dir_path.parents[1]
    documents: list[ParsedDocument] = []

    for file_path in sorted(dir_path.glob("*.md")):
        post = frontmatter.load(file_path)
        title = post.get("title")
        doc_type = post.get("type")
        if not isinstance(title, str) or doc_type not in DOCUMENT_TYPES:
            raise ValueError(f"Document {file_path.name} is missing required frontmatter (title, type).")

        company_name = post.get("company")
        documents.append(
            ParsedDocument(
                source_path=str(file_path.relative_to(repo_root)),
                title=title,
                doc_type=doc_type,
                company_name=company_name if isinstance(company_name, str) else None,
                content=post.content.strip(),
            )
        )
    return documents


async def _resolve_company_id(pool, company_name: str | None) -> int | None:
    if not company_name:
        return None
    row = await pool.fetchrow("SELECT id FROM companies WHERE name = $1", company_name)
    return row["id"] if row else None


async def ingest_documents() -> IngestSummary:
    """Ingests every document under sample-data/documents, replacing any
    prior ingestion (both the Postgres metadata rows and the Qdrant
    collection are recreated from scratch, so re-running never duplicates)."""
    pool = await get_pool()

    run_row = await pool.fetchrow(
        "INSERT INTO ingestion_runs (embedding_model) VALUES ($1) RETURNING id",
        EMBEDDING_MODEL,
    )
    ingestion_run_id = run_row["id"]

    documents_processed = 0
    chunks_created = 0

    try:
        documents = _load_documents()

        # Re-ingesting should not duplicate rows/points: clear prior state first.
        await pool.execute("TRUNCATE documents RESTART IDENTITY CASCADE")
        await recreate_collection()

        for doc in documents:
            company_id = await _resolve_company_id(pool, doc.company_name)
            doc_row = await pool.fetchrow(
                """INSERT INTO documents (source_path, title, doc_type, company_id, content)
                   VALUES ($1, $2, $3, $4, $5) RETURNING id""",
                doc.source_path,
                doc.title,
                doc.doc_type,
                company_id,
                doc.content,
            )
            document_id = doc_row["id"]

            chunks = chunk_text(doc.content)
            if len(chunks) == 0:
                continue

            embeddings = await embed_texts([chunk.content for chunk in chunks])

            points = [
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embeddings[i],
                    payload={
                        "document_id": document_id,
                        "chunk_index": chunk.index,
                        "content": chunk.content,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "document_title": doc.title,
                        "source_path": doc.source_path,
                        "doc_type": doc.doc_type,
                        "company_id": company_id,
                        "company_name": doc.company_name,
                    },
                )
                for i, chunk in enumerate(chunks)
            ]
            await upsert_chunks(points)
            chunks_created += len(points)
            documents_processed += 1

        await pool.execute(
            """UPDATE ingestion_runs
               SET status = 'completed', completed_at = NOW(), documents_processed = $1, chunks_created = $2
               WHERE id = $3""",
            documents_processed,
            chunks_created,
            ingestion_run_id,
        )
        return IngestSummary(
            ingestion_run_id=ingestion_run_id,
            documents_processed=documents_processed,
            chunks_created=chunks_created,
            status="completed",
        )
    except Exception as exc:  # noqa: BLE001 - recorded on the run row, then re-raised as a clean summary
        message = str(exc)
        await pool.execute(
            """UPDATE ingestion_runs
               SET status = 'failed', completed_at = NOW(), documents_processed = $1, chunks_created = $2, error = $3
               WHERE id = $4""",
            documents_processed,
            chunks_created,
            message,
            ingestion_run_id,
        )
        return IngestSummary(
            ingestion_run_id=ingestion_run_id,
            documents_processed=documents_processed,
            chunks_created=chunks_created,
            status="failed",
            error=message,
        )
