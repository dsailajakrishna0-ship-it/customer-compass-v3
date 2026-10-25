"""Parameterized structured CRM queries (ported from apps/api/src/crm/queries.ts).

Plain SQL lookups against the relational tables — no embeddings, no LLM
involved. They back the "structured facts" half of the query-routing split
(see app/chat/router.py): facts that come from here are already correct and
never need a citation, unlike claims retrieved from document chunks.
"""

from dataclasses import dataclass

from app.db import get_pool


@dataclass
class CompanyRef:
    id: int
    name: str


async def list_companies() -> list[CompanyRef]:
    """All companies, used for company-name detection in query routing."""
    pool = await get_pool()
    rows = await pool.fetch("SELECT id, name FROM companies ORDER BY name")
    return [CompanyRef(id=row["id"], name=row["name"]) for row in rows]


@dataclass
class DealFact:
    id: int
    name: str
    amount: str
    status: str
    expected_close_date: str | None


async def get_open_deals(company_id: int) -> list[DealFact]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, name, amount::text AS amount, status, expected_close_date::text AS expected_close_date
           FROM deals
           WHERE company_id = $1 AND status = 'open'
           ORDER BY expected_close_date NULLS LAST""",
        company_id,
    )
    return [
        DealFact(
            id=row["id"],
            name=row["name"],
            amount=row["amount"],
            status=row["status"],
            expected_close_date=row["expected_close_date"],
        )
        for row in rows
    ]


@dataclass
class InteractionFact:
    id: int
    interaction_type: str
    subject: str
    occurred_at: str
    summary: str


# Recent interactions (emails, calls, meetings, support): the "history" evidence for the Stage 10 agent
async def get_recent_interactions(company_id: int, limit: int = 5) -> list[InteractionFact]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, interaction_type, subject, occurred_at::text AS occurred_at, summary
           FROM interactions
           WHERE company_id = $1
           ORDER BY occurred_at DESC
           LIMIT $2""",
        company_id,
        limit,
    )
    return [
        InteractionFact(
            id=row["id"],
            interaction_type=row["interaction_type"],
            subject=row["subject"],
            occurred_at=row["occurred_at"],
            summary=row["summary"],
        )
        for row in rows
    ]


@dataclass
class CompanySummary:
    id: int
    name: str
    industry: str
    relationship_status: str
    open_deals: list[DealFact]
    won_deals_count: int
    lost_deals_count: int


# Structured CRM facts: exact SQL answers from Postgres, so the model doesn't have to guess numbers
async def get_company_summary(company_id: int) -> CompanySummary | None:
    """Structured facts about one company: relationship status, open deals,
    and deal-outcome counts."""
    pool = await get_pool()
    company_row = await pool.fetchrow(
        "SELECT id, name, industry, relationship_status FROM companies WHERE id = $1",
        company_id,
    )
    if not company_row:
        return None

    open_deals = await get_open_deals(company_id)
    deal_count_rows = await pool.fetch(
        "SELECT status, COUNT(*)::text AS count FROM deals WHERE company_id = $1 GROUP BY status",
        company_id,
    )
    counts_by_status = {row["status"]: int(row["count"]) for row in deal_count_rows}

    return CompanySummary(
        id=company_row["id"],
        name=company_row["name"],
        industry=company_row["industry"],
        relationship_status=company_row["relationship_status"],
        open_deals=open_deals,
        won_deals_count=counts_by_status.get("won", 0),
        lost_deals_count=counts_by_status.get("lost", 0),
    )
