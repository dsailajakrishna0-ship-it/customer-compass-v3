"""Stage 8.c read endpoint: review the guardrail detections recorded in
security_audit_log (what was flagged, where, and when)."""

from fastapi import APIRouter, Query

from app.db import get_pool

router = APIRouter(tags=["security"])


@router.get("/security-audit-log")
async def list_security_audit_log(
    limit: int = Query(50, ge=1, le=500),
    event_type: str | None = Query(None, pattern="^(input|document|tool|output)$"),
    pattern: str | None = None,
):
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, event_type, endpoint, pattern, location, excerpt,
                  created_at::text AS created_at
           FROM security_audit_log
           WHERE ($1::text IS NULL OR event_type = $1)
             AND ($2::text IS NULL OR pattern = $2)
           ORDER BY created_at DESC, id DESC
           LIMIT $3""",
        event_type,
        pattern,
        limit,
    )
    return [dict(row) for row in rows]
