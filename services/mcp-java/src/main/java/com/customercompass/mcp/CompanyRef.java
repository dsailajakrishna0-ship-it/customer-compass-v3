package com.customercompass.mcp;

import java.util.List;
import java.util.Locale;
import java.util.Optional;

/** A company's id and name, as listed from the database. */
public record CompanyRef(int id, String name) {

    /**
     * Finds the first company whose name is clearly referenced in free text: any word of the name longer
     * than three characters appearing in the text, ignoring case. This is the same rule as
     * find_mentioned_company in apps/api-py/app/chat/router.py, so "Acme" finds "Acme Fabrication" on both
     * servers.
     */
    public static Optional<CompanyRef> findMentioned(String text, List<CompanyRef> companies) {
        String lower = text.toLowerCase(Locale.ROOT);
        for (CompanyRef company : companies) {
            for (String word : company.name().split("\\s+")) {
                if (word.length() > 3 && lower.contains(word.toLowerCase(Locale.ROOT))) {
                    return Optional.of(company);
                }
            }
        }
        return Optional.empty();
    }
}
