import json

import httpx
import pytest
from lab_common.chat import UnavailableError
from lab_common.crm import CrmClient, find_company


def test_a_word_longer_than_three_characters_finds_the_company():
    companies = [{"id": 1, "name": "Acme Fabrication"}]
    assert find_company("what about ACME?", companies) == companies[0]
    assert (
        find_company("tell me about Bo", [{"id": 2, "name": "Bo Inc"}]) is None
    )  # words of 3 or fewer do not count


def test_summary_has_the_contract_shape(crm_tools):
    answer = json.loads(crm_tools.call("get_company_summary", "Acme"))
    assert answer["status"] == "executed"
    company = answer["company"]
    assert company["name"] == "Acme Fabrication"
    assert company["relationshipStatus"] == "customer"
    assert company["openDeals"] == [
        {
            "name": "Renewal",
            "amount": "48000.00",
            "status": "open",
            "expectedCloseDate": "2026-10-15",
        }
    ]
    assert (company["wonDealsCount"], company["lostDealsCount"]) == (1, 1)


def test_open_deals_has_the_contract_shape(crm_tools):
    answer = json.loads(crm_tools.call("get_open_deals", "Acme"))
    assert answer["companyName"] == "Acme Fabrication"
    assert [d["name"] for d in answer["openDeals"]] == ["Renewal"]


def test_an_unknown_company_is_a_not_found_answer_not_an_error(crm_tools):
    answer = json.loads(crm_tools.call("get_open_deals", "Nobody Ltd"))
    assert answer["status"] == "not_found"


def test_an_unknown_tool_is_refused(crm_tools):
    with pytest.raises(ValueError):
        crm_tools.call("delete_everything", "Acme")


def client(handler):
    return CrmClient("http://crm.test", transport=httpx.MockTransport(handler))


def test_the_client_reads_the_two_routes():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(
            200,
            json=[{"id": 1, "name": "Acme"}]
            if request.url.path.endswith("companies")
            else {"id": 1},
        )

    crm = client(handler)
    assert crm.companies() == [{"id": 1, "name": "Acme"}]
    assert crm.company(1) == {"id": 1}
    assert seen == ["/api/v1/companies", "/api/v1/companies/1"]


def test_a_missing_company_is_none_and_a_server_error_is_unavailable():
    assert client(lambda r: httpx.Response(404)).company(9) is None
    with pytest.raises(UnavailableError) as info:
        client(lambda r: httpx.Response(500, text="secret internal text")).companies()
    assert "secret" not in str(info.value)


def test_an_unreachable_crm_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(UnavailableError):
        client(handler).companies()
