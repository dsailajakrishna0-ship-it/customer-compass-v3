package com.customercompass.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.Test;

class CompanyRefTest {

    private static final List<CompanyRef> COMPANIES = List.of(
            new CompanyRef(1, "Acme Fabrication"), new CompanyRef(2, "Northstar Logistics"), new CompanyRef(3, "Zed Co"));

    @Test
    void aPartialNameFindsTheCompany() {
        assertThat(CompanyRef.findMentioned("Acme", COMPANIES)).contains(COMPANIES.get(0));
        assertThat(CompanyRef.findMentioned("what about NORTHSTAR deals?", COMPANIES)).contains(COMPANIES.get(1));
    }

    @Test
    void theFirstCompanyInListOrderWins() {
        var twins = List.of(new CompanyRef(7, "Delta Works"), new CompanyRef(8, "Delta Labs"));
        assertThat(CompanyRef.findMentioned("delta", twins)).contains(twins.get(0));
    }

    @Test
    void wordsOfThreeCharactersOrFewerNeverMatch() {
        // "Zed Co" has no word longer than three characters, so it can never be found by name
        assertThat(CompanyRef.findMentioned("Zed Co", COMPANIES)).isEmpty();
    }

    @Test
    void anUnknownNameFindsNothing() {
        assertThat(CompanyRef.findMentioned("Globex", COMPANIES)).isEmpty();
        assertThat(CompanyRef.findMentioned("", COMPANIES)).isEmpty();
    }
}
