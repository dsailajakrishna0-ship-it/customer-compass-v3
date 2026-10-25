import { useState } from "react";
import { ingestDocuments as ingestDocumentsRequest } from "../api/documents";
import { ChatPanel } from "../components/chat/ChatPanel";

/** Chat route: the "Ask Compass" panel, including document ingestion controls. */
export function ChatPage() {
  const [ingestStatus, setIngestStatus] = useState<string | null>(null);
  const [isIngesting, setIsIngesting] = useState(false);

  async function ingestDocuments() {
    setIsIngesting(true); setIngestStatus("Ingesting documents…");
    try {
      const body = await ingestDocumentsRequest();
      setIngestStatus(body.status === "completed"
        ? `Ingested ${body.documentsProcessed} documents into ${body.chunksCreated} chunks.`
        : `Ingestion failed: ${body.error ?? "unknown error"}`);
    } catch { setIngestStatus("Could not reach the API to ingest documents."); }
    finally { setIsIngesting(false); }
  }

  return (
    <ChatPanel ingestStatus={ingestStatus} isIngesting={isIngesting} onIngest={() => void ingestDocuments()} />
  );
}
