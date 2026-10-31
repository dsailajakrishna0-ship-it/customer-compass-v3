package com.customercompass.mcp;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.ai.mcp.annotation.McpTool;
import org.springframework.ai.mcp.annotation.McpToolParam;
import org.springframework.stereotype.Component;

/**
 * The four MCP tools. Names, arguments and answers follow contracts/mcp-tools.json, which the FastMCP
 * server follows too.
 *
 * <p>The parameter names are snake_case on purpose: Spring AI takes a tool's argument names from the Java
 * parameter names, and the contract says {@code company_name}, not {@code companyName}.
 */
@Component
@SuppressWarnings("checkstyle:ParameterName")
public class CrmTools {

    private final CrmRepository crm;
    private final RetrievalClient retrieval;

    public CrmTools(CrmRepository crm, RetrievalClient retrieval) {
        this.crm = crm;
        this.retrieval = retrieval;
    }

    @McpTool(
            name = "get_company_summary",
            description = "Get verified CRM facts for a company: industry, relationship status, open deals, "
                    + "and won/lost deal counts.")
    public Map<String, Object> getCompanySummary(
            @McpToolParam(description = "The company's name, as the user wrote it.", required = true) String company_name) {
        Optional<CompanyRef> company = resolve(company_name);
        if (company.isEmpty()) {
            return notFound("get_company_summary", Map.of("company_name", company_name), company_name);
        }
        CrmRepository.CompanySummary summary = crm.summary(company.get().id());
        Map<String, Object> companyView = new LinkedHashMap<>();
        companyView.put("id", summary.id());
        companyView.put("name", summary.name());
        companyView.put("industry", summary.industry());
        companyView.put("relationshipStatus", summary.relationshipStatus());
        companyView.put("openDeals", summary.openDeals());
        companyView.put("wonDealsCount", summary.wonDealsCount());
        companyView.put("lostDealsCount", summary.lostDealsCount());
        crm.audit(
                "get_company_summary",
                Map.of("company_name", company_name),
                "executed",
                "Returned summary for " + summary.name(),
                summary.id());
        return Map.of("status", "executed", "company", companyView);
    }

    @McpTool(
            name = "get_open_deals",
            description = "Get only the open deals for a company (name, amount, status, expected close date).")
    public Map<String, Object> getOpenDeals(
            @McpToolParam(description = "The company's name, as the user wrote it.", required = true) String company_name) {
        Optional<CompanyRef> company = resolve(company_name);
        if (company.isEmpty()) {
            return notFound("get_open_deals", Map.of("company_name", company_name), company_name);
        }
        CrmRepository.CompanySummary summary = crm.summary(company.get().id());
        crm.audit(
                "get_open_deals",
                Map.of("company_name", company_name),
                "executed",
                "Returned " + summary.openDeals().size() + " open deal(s) for " + summary.name(),
                summary.id());
        return Map.of("status", "executed", "companyName", summary.name(), "openDeals", summary.openDeals());
    }

    @McpTool(
            name = "search_documents",
            description = "Search CRM interaction documents (emails, calls, support tickets, meeting notes) "
                    + "semantically. Optionally scope to one company.")
    public Map<String, Object> searchDocuments(
            @McpToolParam(description = "What to look for in the interaction documents.", required = true) String query,
            @McpToolParam(description = "Only search this company's documents.", required = false) String company_name) {
        return retrieval.search(query, company_name);
    }

    @McpTool(
            name = "create_followup_task",
            description = "Propose (confirm=false, the default) or create (confirm=true) a follow-up task for a "
                    + "company. Only pass confirm=true after the user has explicitly confirmed the proposed task "
                    + "in their latest message.")
    public Map<String, Object> createFollowupTask(
            @McpToolParam(description = "The company the follow-up is for.", required = true) String company_name,
            @McpToolParam(description = "What the follow-up task is.", required = true) String note,
            @McpToolParam(description = "true only after the user confirmed.", required = false) Boolean confirm) {
        boolean confirmed = Boolean.TRUE.equals(confirm);
        Map<String, Object> asked = new LinkedHashMap<>();
        asked.put("company_name", company_name);
        asked.put("note", note);
        Optional<CompanyRef> company = resolve(company_name);
        if (company.isEmpty()) {
            return notFound("create_followup_task", asked, company_name);
        }
        CompanyRef found = company.get();
        asked.put("confirm", confirmed);
        if (!confirmed) {
            crm.audit("create_followup_task", asked, "proposed", "Proposed task for " + found.name() + ": " + note, found.id());
            return Map.of(
                    "status", "proposed",
                    "message", "Task not yet created -- ask the user to confirm before calling this tool again.",
                    "proposedTask", Map.of("companyName", found.name(), "note", note));
        }
        CrmRepository.Task task = crm.createTask(found.id(), note);
        crm.audit("create_followup_task", asked, "confirmed", "Created task #" + task.id() + " for " + found.name(), found.id());
        return Map.of(
                "status", "confirmed",
                "task", Map.of(
                        "id", task.id(),
                        "companyName", found.name(),
                        "note", note,
                        "status", task.status(),
                        "createdAt", task.createdAt()));
    }

    private Optional<CompanyRef> resolve(String companyName) {
        List<CompanyRef> companies = crm.listCompanies();
        return CompanyRef.findMentioned(companyName, companies);
    }

    private Map<String, Object> notFound(String tool, Map<String, Object> arguments, String companyName) {
        String message = "No company matching \"" + companyName + "\" was found.";
        crm.audit(tool, arguments, "error", message, null);
        return Map.of("status", "not_found", "message", message);
    }
}
