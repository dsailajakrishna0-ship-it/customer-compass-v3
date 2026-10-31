package com.customercompass.mcp;

import java.util.List;
import java.util.Map;

/** The database operations the tools need. The schema is owned by the Python API's Alembic migrations. */
public interface CrmRepository {

    /** All companies, ordered by name. */
    List<CompanyRef> listCompanies();

    CompanySummary summary(int companyId);

    /** Inserts an open task and returns it. */
    Task createTask(int companyId, String note);

    /** Records one tool call in tool_audit_log (the same table the Python server writes). */
    void audit(String tool, Map<String, Object> arguments, String status, String resultSummary, Integer companyId);

    record Deal(String name, String amount, String status, String expectedCloseDate) {}

    record CompanySummary(
            int id,
            String name,
            String industry,
            String relationshipStatus,
            List<Deal> openDeals,
            int wonDealsCount,
            int lostDealsCount) {}

    record Task(int id, String status, String createdAt) {}
}
