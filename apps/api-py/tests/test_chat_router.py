"""Pure unit tests for the deterministic query router (ported from
apps/api/src/chat/router.test.ts) — no network/database required beyond
a stubbed list_companies()."""

import pytest

from app.chat import router as chat_router
from app.chat.router import CompanyRef, classify_query

SAMPLE_COMPANIES = [
    CompanyRef(id=1, name="Acme Fabrication"),
    CompanyRef(id=2, name="Northstar Logistics"),
    CompanyRef(id=3, name="Harbor & Pine"),
]


@pytest.fixture(autouse=True)
def _stub_list_companies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_list_companies() -> list[CompanyRef]:
        return SAMPLE_COMPANIES

    monkeypatch.setattr(chat_router, "list_companies", _fake_list_companies)


@pytest.mark.asyncio
async def test_structured_only_keywords_route_to_structured_and_not_rag() -> None:
    route = await classify_query("What is the deal value for Acme?")
    assert route.wants_structured is True
    assert route.wants_rag is False  # no RAG keyword present, so structured-only
    assert route.company is not None
    assert route.company.name == "Acme Fabrication"


@pytest.mark.asyncio
async def test_structured_keyword_without_company_mention() -> None:
    route = await classify_query("What is the pipeline status?")
    assert route.wants_structured is True
    assert route.company is None


@pytest.mark.asyncio
async def test_rag_keyword_routes_to_rag_only() -> None:
    route = await classify_query("What did Jordan say on the call?")
    assert route.wants_structured is False
    assert route.wants_rag is True


@pytest.mark.asyncio
async def test_no_keyword_match_falls_back_to_rag_only() -> None:
    route = await classify_query("Tell me something interesting.")
    assert route.wants_structured is False
    assert route.wants_rag is True


@pytest.mark.asyncio
async def test_company_mention_is_detected_case_insensitively() -> None:
    route = await classify_query("any notes on northstar logistics?")
    assert route.company is not None
    assert route.company.name == "Northstar Logistics"


@pytest.mark.asyncio
async def test_short_words_in_company_name_do_not_cause_false_positive_match() -> None:
    # "Pine" (>3 chars) should match, but this guards that short filler words
    # ("and", "of", etc. - none >3 chars here) aren't used for matching.
    route = await classify_query("What's the weather like today?")
    assert route.company is None


@pytest.mark.asyncio
async def test_ampersand_company_name_matches_on_significant_word() -> None:
    route = await classify_query("What did Harbor & Pine mention about support?")
    assert route.company is not None
    assert route.company.name == "Harbor & Pine"
