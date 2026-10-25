"""Smoke test for the FastAPI skeleton's /health endpoint.

Requires a reachable Postgres (see apps/api-py/README or the repo-root
docker-compose.yml: `docker compose up -d db`), matching how apps/api's own
test suite assumes a live dependency isn't needed for unit tests but this
integration-style check does need the real database.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_ok() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
