package com.customercompass.mcp;

import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.json.JsonMapper;

/** Postgres access with the same SQL as apps/api-py/app/crm/queries.py and app/mcp/tools.py. */
@Repository
public class JdbcCrmRepository implements CrmRepository {

    private final JdbcClient jdbc;
    private final JsonMapper json = JsonMapper.builder().build();

    public JdbcCrmRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public List<CompanyRef> listCompanies() {
        return jdbc.sql("SELECT id, name FROM companies ORDER BY name")
                .query((rs, n) -> new CompanyRef(rs.getInt("id"), rs.getString("name")))
                .list();
    }

    @Override
    public CompanySummary summary(int companyId) {
        var company = jdbc.sql("SELECT id, name, industry, relationship_status FROM companies WHERE id = :id")
                .param("id", companyId)
                .query((rs, n) -> new String[] {
                    rs.getString("name"), rs.getString("industry"), rs.getString("relationship_status")
                })
                .single();
        List<Deal> open = jdbc.sql(
                        """
                        SELECT name, amount::text AS amount, status, expected_close_date::text AS expected_close_date
                        FROM deals
                        WHERE company_id = :id AND status = 'open'
                        ORDER BY expected_close_date NULLS LAST""")
                .param("id", companyId)
                .query((rs, n) -> new Deal(
                        rs.getString("name"),
                        rs.getString("amount"),
                        rs.getString("status"),
                        rs.getString("expected_close_date")))
                .list();
        Map<String, Integer> counts = new java.util.HashMap<>();
        jdbc.sql("SELECT status, COUNT(*)::int AS count FROM deals WHERE company_id = :id GROUP BY status")
                .param("id", companyId)
                .query((rs, n) -> {
                    counts.put(rs.getString("status"), rs.getInt("count"));
                    return null;
                })
                .list();
        return new CompanySummary(
                companyId, company[0], company[1], company[2], open, counts.getOrDefault("won", 0), counts.getOrDefault("lost", 0));
    }

    @Override
    public Task createTask(int companyId, String note) {
        return jdbc.sql(
                        "INSERT INTO tasks (company_id, note) VALUES (:company, :note)"
                                + " RETURNING id, status, created_at::text AS created_at")
                .param("company", companyId)
                .param("note", note)
                .query((rs, n) -> new Task(rs.getInt("id"), rs.getString("status"), rs.getString("created_at")))
                .single();
    }

    @Override
    public void audit(String tool, Map<String, Object> arguments, String status, String resultSummary, Integer companyId) {
        jdbc.sql(
                        """
                        INSERT INTO tool_audit_log (tool_name, arguments, status, result_summary, company_id)
                        VALUES (:tool, CAST(:arguments AS jsonb), :status, :summary, :company)""")
                .param("tool", tool)
                .param("arguments", json.writeValueAsString(arguments))
                .param("status", status)
                .param("summary", resultSummary)
                .param("company", companyId)
                .update();
    }
}
