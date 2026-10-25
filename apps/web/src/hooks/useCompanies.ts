import { useEffect, useState } from "react";
import { getCompany, listCompanies } from "../api/companies";
import type { Company, Detail } from "../types";

/** Loads the company list once, and exposes a selectCompany(id) action to load its detail view. */
export function useCompanies(): {
  companies: Company[];
  error: string | null;
  selected: Detail | null;
  selectCompany: (id: number) => Promise<void>;
} {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Detail | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setCompanies(await listCompanies());
      } catch {
        setError("Could not reach the API. Start PostgreSQL and the API, then refresh.");
      }
    }
    void load();
  }, []);

  async function selectCompany(id: number) {
    setSelected(await getCompany(id));
  }

  return { companies, error, selected, selectCompany };
}
