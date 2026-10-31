package com.customercompass.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class CrmToolsTest {

    private FakeCrm crm;
    private CrmTools tools;
    private String searchedQuery;
    private String searchedCompany;

    @BeforeEach
    void setUp() {
        crm = new FakeCrm();
        tools = new CrmTools(crm, (query, company) -> {
            searchedQuery = query;
            searchedCompany = company;
            return Map.of("status", "executed", "results", java.util.List.of());
        });
    }

    @Test
    void aTaskIsOnlyProposedWithoutConfirmAndNothingIsWritten() {
        Map<String, Object> result = tools.createFollowupTask("Acme", "Call them", null);
        assertThat(result).containsEntry("status", "proposed");
        assertThat(crm.createdTasks).isEmpty();
        assertThat(crm.audits).singleElement().satisfies(a -> {
            assertThat(a.status()).isEqualTo("proposed");
            assertThat(a.arguments()).containsEntry("confirm", false);
        });
    }

    @Test
    void confirmFalseIsTheSameAsOmittingIt() {
        assertThat(tools.createFollowupTask("Acme", "x", false)).containsEntry("status", "proposed");
        assertThat(crm.createdTasks).isEmpty();
    }

    @Test
    void aConfirmedTaskIsWrittenOnceAndAudited() {
        Map<String, Object> result = tools.createFollowupTask("Acme", "Call them", true);
        assertThat(result).containsEntry("status", "confirmed");
        assertThat(crm.createdTasks).containsExactly("1:Call them");
        assertThat(crm.audits).singleElement().satisfies(a -> assertThat(a.status()).isEqualTo("confirmed"));
    }

    @Test
    void anUnknownCompanyIsNotFoundForEveryToolAndNothingIsWritten() {
        assertThat(tools.getCompanySummary("Globex"))
                .containsEntry("status", "not_found")
                .containsEntry("message", "No company matching \"Globex\" was found.");
        assertThat(tools.getOpenDeals("Globex")).containsEntry("status", "not_found");
        assertThat(tools.createFollowupTask("Globex", "x", true)).containsEntry("status", "not_found");
        assertThat(crm.createdTasks).isEmpty();
        assertThat(crm.audits).hasSize(3).allSatisfy(a -> {
            assertThat(a.status()).isEqualTo("error");
            assertThat(a.companyId()).isNull();
        });
    }

    @Test
    void openDealsNameTheCompanyAndAreAudited() {
        Map<String, Object> result = tools.getOpenDeals("Acme");
        assertThat(result).containsEntry("companyName", "Acme Fabrication");
        assertThat(crm.audits).singleElement().satisfies(a -> {
            assertThat(a.tool()).isEqualTo("get_open_deals");
            assertThat(a.summary()).isEqualTo("Returned 1 open deal(s) for Acme Fabrication");
        });
    }

    @Test
    void searchIsHandedToTheRetrievalClient() {
        tools.searchDocuments("pricing", "Acme");
        assertThat(searchedQuery).isEqualTo("pricing");
        assertThat(searchedCompany).isEqualTo("Acme");
        tools.searchDocuments("anything", null);
        assertThat(searchedCompany).isNull();
    }
}
