"""Stage 9 read endpoints: inspect follow-up tasks the MCP tool created, and
the full tool-call audit trail -- lets a human verify what the tool-calling
copilot actually did, same purpose Stage 7/8's usage/guardrail telemetry
serve for the other routes.
"""

import json

from fastapi import APIRouter

from app.db import get_pool

router = APIRouter(tags=["tasks"])


@router.get("/tasks")
async def list_tasks(company_id: int | None = None):
    pool = await get_pool()
    if company_id is not None:
        rows = await pool.fetch(
            """SELECT t.id, t.company_id, c.name AS company_name, t.note, t.status,
                      t.created_at::text AS created_at
               FROM tasks t JOIN companies c ON c.id = t.company_id
               WHERE t.company_id = $1
               ORDER BY t.created_at DESC""",
            company_id,
        )
    else:
        rows = await pool.fetch(
            """SELECT t.id, t.company_id, c.name AS company_name, t.note, t.status,
                      t.created_at::text AS created_at
               FROM tasks t JOIN companies c ON c.id = t.company_id
               ORDER BY t.created_at DESC"""
        )
    return [dict(row) for row in rows]


# Shows the audit trail of MCP tool calls recorded in Postgres
@router.get("/tool-audit-log")
async def list_tool_audit_log(limit: int = 50):
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, tool_name, arguments, status, result_summary, company_id,
                  created_at::text AS created_at
           FROM tool_audit_log
           ORDER BY created_at DESC
           LIMIT $1""",
        limit,
    )
    return [{**dict(row), "arguments": json.loads(row["arguments"])} for row in rows]
