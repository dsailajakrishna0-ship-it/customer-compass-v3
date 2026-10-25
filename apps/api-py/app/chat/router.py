"""Deterministic, explainable query routing (ported from
apps/api/src/chat/router.ts).

Decides whether a question needs a structured CRM fact lookup (SQL), a
document-retrieval lookup (RAG), both, or — if neither keyword set matches —
falls back to RAG-only, preserving the grounded-chat default behavior. The
routing is a plain keyword/substring match rather than an LLM call, so it
stays fast, free, and trivially observable instead of being another opaque
model decision.

Company scoping (for the "never retrieve another customer's material"
acceptance criterion) is detected the same way: by matching a significant
word from a known company name against the question text.
"""

from dataclasses import dataclass

from app.crm.queries import CompanyRef, list_companies

# Router keywords: deal/pipeline words send the question to SQL CRM facts instead of document search
STRUCTURED_KEYWORDS = [
    "deal",
    "deals",
    "pipeline",
    "amount",
    "value",
    "status of",
    "close date",
    "revenue",
    "won",
    "lost",
    "relationship status",
]

# Router keywords: "said/email/call" style words send the question to RAG document search
RAG_KEYWORDS = [
    "said",
    "say",
    "says",
    "mention",
    "discuss",
    "told",
    "email",
    "call",
    "note",
    "conversation",
    "feedback",
    "asked",
    "requested",
    "complain",
]


@dataclass
class QueryRoute:
    wants_structured: bool
    wants_rag: bool
    company: CompanyRef | None


def _matches_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def find_mentioned_company(text: str, companies: list[CompanyRef]) -> CompanyRef | None:
    """Finds the first company whose name is clearly referenced in free text --
    a question (query routing) or a tool argument (Stage 9 MCP tools' company
    name resolution). Exported so app/mcp/tools.py can reuse this exact
    heuristic instead of duplicating it."""
    lower = text.lower()
    for company in companies:
        significant_words = [word for word in company.name.split() if len(word) > 3]
        if any(word.lower() in lower for word in significant_words):
            return company
    return None


async def classify_query(question: str) -> QueryRoute:
    lower = question.lower()
    companies = await list_companies()
    company = find_mentioned_company(question, companies)

    wants_structured = _matches_any(lower, STRUCTURED_KEYWORDS)
    wants_rag = _matches_any(lower, RAG_KEYWORDS) or not wants_structured

    return QueryRoute(wants_structured=wants_structured, wants_rag=wants_rag, company=company)
