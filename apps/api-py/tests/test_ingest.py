"""Integration test for the full ingestion pipeline (parse -> chunk -> embed
-> store). Requires live Postgres, Qdrant, and a real GOOGLE_API_KEY (see
apps/api-py/.env.example) — skipped automatically when the key isn't set so
the rest of the suite still runs without network/cloud dependencies.
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

requires_google_key = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set; skipping live embedding/ingestion test.",
)


@requires_google_key
@pytest.mark.asyncio
async def test_ingest_then_list_documents() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ingest_response = await client.post("/documents/ingest")
        assert ingest_response.status_code == 200, ingest_response.text
        summary = ingest_response.json()
        assert summary["status"] == "completed"
        assert summary["documentsProcessed"] > 0
        assert summary["chunksCreated"] > 0

        list_response = await client.get("/documents")
        assert list_response.status_code == 200
        documents = list_response.json()
        assert len(documents) == summary["documentsProcessed"]
        assert all(doc["chunkCount"] > 0 for doc in documents)

        runs_response = await client.get("/documents/ingestion-runs")
        assert runs_response.status_code == 200
        runs = runs_response.json()
        assert runs[0]["status"] == "completed"
