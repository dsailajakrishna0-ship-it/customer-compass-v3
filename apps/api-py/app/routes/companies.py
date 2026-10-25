"""Company list/detail routes (ported from apps/api/src/app.ts's
GET /api/companies and GET /api/companies/:id).

Keeps the same snake_case field names the Express route used (node-postgres
returns column names as-is, unlike the chat/CRM routes which hand-build
camelCase JSON) so the existing frontend types (apps/web/src/types/index.ts:
Company, Deal, Contact, Interaction) don't need to change for this cutover.
"""

from fastapi import APIRouter, HTTPException

from app.db import get_pool

# Plain SQL reads from Postgres - no AI involved, powers the company explorer UI
router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("")
async def list_companies():
    """Lists all companies with their deal/interaction counts, for the
    dashboard's company list view."""
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT c.id, c.name, c.industry, c.relationship_status,
                  COUNT(DISTINCT d.id)::int AS deal_count,
                  COUNT(DISTINCT i.id)::int AS interaction_count
           FROM companies c
           LEFT JOIN deals d ON d.company_id = c.id
           LEFT JOIN interactions i ON i.company_id = c.id
           GROUP BY c.id
           ORDER BY c.name"""
    )
    return [dict(row) for row in rows]


@router.get("/{company_id}")
async def get_company(company_id: int):
    """Returns a single company's profile plus its contacts/deals/interactions,
    for the dashboard's company detail view."""
    pool = await get_pool()

    company = await pool.fetchrow(
        "SELECT id, name, industry, website, relationship_status FROM companies WHERE id = $1",
        company_id,
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found.")

    contacts_rows = await pool.fetch(
        "SELECT id, full_name, job_title, email FROM contacts WHERE company_id = $1 ORDER BY full_name",
        company_id,
    )
    deals_rows = await pool.fetch(
        """SELECT id, name, amount, status, expected_close_date::text AS expected_close_date
           FROM deals WHERE company_id = $1 ORDER BY expected_close_date DESC""",
        company_id,
    )
    interactions_rows = await pool.fetch(
        """SELECT id, interaction_type, subject, occurred_at, summary
           FROM interactions WHERE company_id = $1 ORDER BY occurred_at DESC""",
        company_id,
    )

    return {
        **dict(company),
        "contacts": [dict(r) for r in contacts_rows],
        "deals": [{**dict(r), "amount": str(r["amount"])} for r in deals_rows],
        "interactions": [
            {**dict(r), "occurred_at": r["occurred_at"].isoformat() if r["occurred_at"] else None}
            for r in interactions_rows
        ],
    }
