import pytest
from lab_common.crm import CrmTools


class FakeCrm:
    """The application's CRM routes, as the tests need them."""

    def companies(self):
        return [{"id": 1, "name": "Acme Fabrication"}, {"id": 2, "name": "Bo Inc"}]

    def company(self, company_id):
        if company_id != 1:
            return None
        return {
            "id": 1,
            "name": "Acme Fabrication",
            "industry": "Manufacturing",
            "relationship_status": "customer",
            "deals": [
                {
                    "name": "Renewal",
                    "amount": "48000.00",
                    "status": "open",
                    "expected_close_date": "2026-10-15",
                },
                {
                    "name": "Old deal",
                    "amount": "5.00",
                    "status": "won",
                    "expected_close_date": None,
                },
                {
                    "name": "Lost deal",
                    "amount": "9.00",
                    "status": "lost",
                    "expected_close_date": None,
                },
            ],
        }


@pytest.fixture
def crm_tools() -> CrmTools:
    return CrmTools(FakeCrm())  # type: ignore[arg-type]
