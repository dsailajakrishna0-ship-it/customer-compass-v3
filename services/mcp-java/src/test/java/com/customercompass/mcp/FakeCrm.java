package com.customercompass.mcp;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** An in-memory stand-in for the database, seeded with the same demo values the contract expects. */
class FakeCrm implements CrmRepository {

    record Audit(String tool, Map<String, Object> arguments, String status, String summary, Integer companyId) {}

    final List<Audit> audits = new ArrayList<>();
    final List<String> createdTasks = new ArrayList<>();

    @Override
    public List<CompanyRef> listCompanies() {
        return List.of(new CompanyRef(1, "Acme Fabrication"), new CompanyRef(2, "Northstar Logistics"));
    }

    @Override
    public CompanySummary summary(int companyId) {
        if (companyId == 1) {
            return new CompanySummary(
                    1,
                    "Acme Fabrication",
                    "Manufacturing",
                    "customer",
                    List.of(new Deal("Premium Operations Plan renewal", "48000.00", "open", "2026-10-15")),
                    1,
                    0);
        }
        return new CompanySummary(2, "Northstar Logistics", "Logistics", "lead", List.of(), 0, 0);
    }

    @Override
    public Task createTask(int companyId, String note) {
        createdTasks.add(companyId + ":" + note);
        return new Task(createdTasks.size(), "open", "2026-10-31 10:00:00+00");
    }

    @Override
    public void audit(String tool, Map<String, Object> arguments, String status, String resultSummary, Integer companyId) {
        audits.add(new Audit(tool, arguments, status, resultSummary, companyId));
    }
}
