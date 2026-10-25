import type { Citation } from "../../types";

/** Numbered, citable sources list rendered below a RAG/CRM-mode assistant message. */
export function CitationList({ citations }: { citations: Citation[] }) {
  return (
    // Citations come from Qdrant similarity search; the number shows how close each chunk matched
    <ol className="citations">
      {citations.map((citation) => (
        <li key={citation.number}>
          [{citation.number}] {citation.title}
          {citation.companyName ? ` · ${citation.companyName}` : ""}
          {" "}({citation.docType}, similarity {citation.similarity.toFixed(2)})
        </li>
      ))}
    </ol>
  );
}
