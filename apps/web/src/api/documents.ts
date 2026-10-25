import { apiPost } from "./client";
import type { IngestSummary } from "../types";

export function ingestDocuments(): Promise<IngestSummary> {
  return apiPost<IngestSummary>("/api/v1/documents/ingest");
}
