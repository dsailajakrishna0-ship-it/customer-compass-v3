"""Stage 8.c: durable security audit log. Every guardrail detection (input,
document, tool result, model output) is written to Postgres so flagged
attempts can be reviewed later, not just seen in a log line. Writing never
breaks a chat request: failures are logged and swallowed."""

import logging
import os

from app.db import get_pool
from app.guardrails.prompt_guard import GuardEvent

logger = logging.getLogger("app.guardrails.audit")

RETENTION_DAYS = int(os.environ.get("SECURITY_AUDIT_RETENTION_DAYS", "90"))

# Also in db/init.sql; created here too so existing Docker volumes get it without a reset
_SCHEMA = """
CREATE TABLE IF NOT EXISTS security_audit_log (
  id SERIAL PRIMARY KEY,
  event_type TEXT NOT NULL CHECK (event_type IN ('input', 'document', 'tool', 'output')),
  endpoint TEXT NOT NULL,
  pattern TEXT NOT NULL,
  location TEXT NOT NULL,
  excerpt TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


async def ensure_schema_and_purge() -> None:
    """Startup hook: create the table if missing and delete rows past retention."""
    try:
        pool = await get_pool()
        await pool.execute(_SCHEMA)
        await pool.execute(
            "DELETE FROM security_audit_log WHERE created_at < NOW() - make_interval(days => $1)",
            RETENTION_DAYS,
        )
    except Exception as exc:  # noqa: BLE001 - DB may be down at boot; /health reports that
        logger.warning("security_audit_log setup skipped: %s", exc)


async def record_events(endpoint: str, events: list[GuardEvent]) -> None:
    if not events:
        return
    try:
        pool = await get_pool()
        await pool.executemany(
            "INSERT INTO security_audit_log (event_type, endpoint, pattern, location, excerpt)"
            " VALUES ($1, $2, $3, $4, $5)",
            [(e.source, endpoint, e.pattern, e.location, e.snippet) for e in events],
        )
    except Exception as exc:  # noqa: BLE001 - auditing must never fail the request
        logger.warning("security_audit_log write failed: %s", exc)
