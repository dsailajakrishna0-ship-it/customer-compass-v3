"""POST /documents/ingest keeps its contract when a run fails: the body is the summary, and `error`
is plain text. (The web app prints it; a nested object showed as "[object Object]".)"""

import json

import pytest

from app.rag.ingest import IngestSummary
from app.routes import documents


def summary(**kwargs) -> IngestSummary:
    base = dict(
        ingestion_run_id=3, documents_processed=0, chunks_created=0, status="failed", error=None
    )
    return IngestSummary(**{**base, **kwargs})


@pytest.mark.asyncio
async def test_a_failed_run_returns_the_summary_with_a_plain_text_error(monkeypatch):
    async def failed():
        return summary(error="GOOGLE_API_KEY is not set.")

    monkeypatch.setattr(documents, "ingest_documents", failed)
    response = await documents.ingest()
    assert response.status_code == 502
    assert json.loads(response.body) == {
        "ingestionRunId": 3,
        "documentsProcessed": 0,
        "chunksCreated": 0,
        "status": "failed",
        "error": "GOOGLE_API_KEY is not set.",
    }


@pytest.mark.asyncio
async def test_a_completed_run_is_a_200(monkeypatch):
    async def done():
        return summary(status="completed", documents_processed=7, chunks_created=42)

    monkeypatch.setattr(documents, "ingest_documents", done)
    response = await documents.ingest()
    assert response.status_code == 200 and json.loads(response.body)["chunksCreated"] == 42
