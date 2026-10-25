"""Shared pytest fixtures.

Each async test gets its own event loop (pytest-asyncio's default, function-
scoped). app.db and app.rag.qdrant_store keep process-wide singleton
connections (a Postgres pool and a Qdrant client) for reuse across requests
within one running server — but that pattern breaks across tests, since a
connection/client created on one test's event loop can't be reused once that
loop is closed. This fixture resets both singletons after every test so each
one starts clean on its own loop.
"""

import pytest_asyncio

from app.db import close_pool
from app.rag.qdrant_store import close_client


@pytest_asyncio.fixture(autouse=True)
async def _reset_singletons():
    yield
    await close_pool()
    await close_client()
