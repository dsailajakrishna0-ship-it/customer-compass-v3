import { useState } from "react";
import { CompanyExplorer } from "../components/companies/CompanyExplorer";

/** Dashboard route: the company sidebar + detail pane. */
export function DashboardPage() {
  const [error, setError] = useState<string | null>(null);

  return (
    <>
      {error && <p className="error">{error}</p>}
      <CompanyExplorer onError={setError} />
    </>
  );
}
