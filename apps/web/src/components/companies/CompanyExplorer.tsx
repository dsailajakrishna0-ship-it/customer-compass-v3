import { useEffect } from "react";
import { useCompanies } from "../../hooks/useCompanies";
import { CompanyList } from "./CompanyList";
import { CompanyDetail, CompanyDetailEmptyState } from "./CompanyDetail";

/** Composes the company sidebar and detail pane; owns its own data via useCompanies. */
export function CompanyExplorer({ onError }: { onError: (message: string | null) => void }) {
  const { companies, error, selected, selectCompany } = useCompanies();

  // Surface load errors to the parent so they render above the whole layout,
  // matching the original app's single top-level error banner. Runs as an
  // effect (not during render) to avoid updating a different component's
  // state mid-render.
  useEffect(() => { onError(error); }, [error, onError]);

  return (
    <section className="layout">
      <CompanyList companies={companies} selectedId={selected?.id} onSelect={(id) => void selectCompany(id)} />
      <article>{selected ? <CompanyDetail company={selected} /> : <CompanyDetailEmptyState />}</article>
    </section>
  );
}
