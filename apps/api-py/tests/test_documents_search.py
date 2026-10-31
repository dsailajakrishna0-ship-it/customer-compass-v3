"""POST /documents/search: the endpoint the Spring Boot MCP server uses for document search."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routes import documents


@pytest.mark.asyncio
async def test_search_returns_exactly_what_the_fastmcp_tool_returns(monkeypatch):
    seen = {}

    async def fake_tool(query, company_name=None):
        seen.update(query=query, company_name=company_name)
        return {"status": "executed", "results": []}

    monkeypatch.setattr(documents, "search_documents_tool", fake_tool)
    request = documents.SearchRequest.model_validate({"query": "pricing", "companyName": "Acme"})
    assert await documents.search(request) == {"status": "executed", "results": []}
    assert seen == {"query": "pricing", "company_name": "Acme"}


def test_the_company_is_optional_and_the_query_is_required():
    assert documents.SearchRequest.model_validate({"query": "x"}).company_name is None
    with pytest.raises(ValidationError):
        documents.SearchRequest.model_validate({"query": ""})
    with pytest.raises(ValidationError):
        documents.SearchRequest.model_validate({})


@pytest.mark.asyncio
async def test_a_missing_embeddings_key_is_a_503_with_the_reason(monkeypatch):
    async def no_key(*_a, **_k):
        raise RuntimeError("GOOGLE_API_KEY is not set.")

    monkeypatch.setattr(documents, "search_documents_tool", no_key)
    with pytest.raises(HTTPException) as exc:
        await documents.search(documents.SearchRequest.model_validate({"query": "x"}))
    assert exc.value.status_code == 503 and "GOOGLE_API_KEY" in exc.value.detail
