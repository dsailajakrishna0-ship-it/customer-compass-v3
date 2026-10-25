"""Postgres connection pool (structured/relational data only — not vectors).

Mirrors apps/api/src/db.ts: a single shared async connection pool, configured
via DATABASE_URL, defaulting to the same local dev database the Express API
uses.
"""

import os

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://customer_compass:customer_compass_dev@localhost:5432/customer_compass",
)

# Postgres (via asyncpg): holds relational CRM data (companies, deals, tasks), not embeddings
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Returns the shared connection pool, creating it on first use."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool


async def close_pool() -> None:
    """Closes the shared connection pool, if it was created."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
