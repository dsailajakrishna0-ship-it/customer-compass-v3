import type { Company } from "../../types";

type CompanyListProps = {
  companies: Company[];
  selectedId: number | undefined;
  onSelect: (id: number) => void;
};

/** Sidebar list of companies; highlights the currently selected one. */
export function CompanyList({ companies, selectedId, onSelect }: CompanyListProps) {
  return (
    <aside>
      <h2>Companies</h2>
      {companies.map((company) => (
        <button
          className={selectedId === company.id ? "company selected" : "company"}
          key={company.id}
          onClick={() => onSelect(company.id)}
        >
          <strong>{company.name}</strong>
          <span>{company.industry} · {company.relationship_status}</span>
          <small>{company.deal_count} deals · {company.interaction_count} interactions</small>
        </button>
      ))}
    </aside>
  );
}
