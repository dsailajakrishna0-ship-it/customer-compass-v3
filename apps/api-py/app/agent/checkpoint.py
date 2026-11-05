"""Where a paused agent run is saved (Stage 3.2b): LangGraph's Postgres checkpointer.

A run that reaches the human-approval gate stops and is written to Postgres, so it survives an API
restart. The library creates its own tables on first use (`setup()`), over the `psycopg` driver the
project already depends on. One small connection pool is shared by the whole process, like
`app.db.get_pool` for the CRM data.
"""

import hashlib

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

_pool: AsyncConnectionPool | None = None
_saver: AsyncPostgresSaver | None = None


async def get_checkpointer() -> AsyncPostgresSaver:
    """The shared checkpointer, created (and its tables set up) on first use."""
    global _pool, _saver
    if _saver is None:
        # autocommit and dict rows are what the library's own setup requires
        pool = AsyncConnectionPool(
            get_settings().database_url,
            min_size=1,
            max_size=3,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await pool.open()
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await saver.setup()
        _pool, _saver = pool, saver
    return _saver


async def close_checkpointer() -> None:
    global _pool, _saver
    if _pool is not None:
        await _pool.close()
    _pool = _saver = None


def thread_id(company_name: str, note: str) -> str:
    """The id of a run, derived from what the user will confirm.

    The API contract has no run id (ADR 0018), so /recommend and /confirm both compute the same id
    from the company and the proposed note. Case and surrounding spaces do not matter."""
    key = f"{company_name.strip().casefold()}|{note.strip()}"
    return "followup-" + hashlib.sha256(key.encode()).hexdigest()[:32]
