import type { Detail } from "../../types";

/** Full detail view for a selected company: contacts, deals, interaction history. */
export function CompanyDetail({ company }: { company: Detail }) {
  return (
    <>
      <div className="detail-heading">
        <div>
          <p className="eyebrow">{company.relationship_status}</p>
          <h2>{company.name}</h2>
          <p>{company.industry}{company.website && ` · ${company.website}`}</p>
        </div>
      </div>
      <section>
        <h3>Contacts</h3>
        <ul>
          {company.contacts.map((c) => (
            <li key={c.id}>
              <strong>{c.full_name}</strong> — {c.job_title ?? "Contact"}
              <br />
              <small>{c.email}</small>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h3>Deals</h3>
        {company.deals.map((d) => (
          <div className="card" key={d.id}>
            <strong>{d.name}</strong>
            <span>{d.status} · ${Number(d.amount).toLocaleString()} · expected {d.expected_close_date ?? "not set"}</span>
          </div>
        ))}
      </section>
      <section>
        <h3>Interactions</h3>
        {company.interactions.map((i) => (
          <div className="card" key={i.id}>
            <strong>{i.subject}</strong>
            <span>{i.interaction_type} · {new Date(i.occurred_at).toLocaleDateString()}</span>
            <p>{i.summary}</p>
          </div>
        ))}
      </section>
    </>
  );
}

/** Placeholder shown in the detail pane before any company is selected. */
export function CompanyDetailEmptyState() {
  return (
    <div className="empty">
      <h2>Select a company</h2>
      <p>Explore its contacts, deals, and interaction history.</p>
    </div>
  );
}
