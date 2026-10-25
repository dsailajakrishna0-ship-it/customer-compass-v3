import type { CrmFact } from "../../types";

/** "Facts (from CRM database)" panel shown above citations when a CRM-mode answer includes verified structured facts. */
export function CrmFactsPanel({ facts }: { facts: CrmFact }) {
  return (
    // Facts are exact rows from Postgres, not model-generated text
    <div className="crm-facts">
      <strong>Facts (from CRM database)</strong>
      <p>{facts.name} — {facts.industry} · {facts.relationshipStatus}</p>
      {facts.openDeals.length > 0 ? (
        <ul>
          {facts.openDeals.map((deal) => (
            <li key={deal.id}>
              {deal.name} · ${Number(deal.amount).toLocaleString()} · expected {deal.expectedCloseDate ?? "not set"}
            </li>
          ))}
        </ul>
      ) : (
        <p>No open deals.</p>
      )}
      <small>{facts.wonDealsCount} won · {facts.lostDealsCount} lost</small>
    </div>
  );
}
