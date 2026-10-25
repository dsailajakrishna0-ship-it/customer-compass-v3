/**
 * Minimal fetch wrapper: central base URL and shared JSON parsing so
 * feature API modules (companies.ts, chat.ts, documents.ts) stay thin.
 *
 * Mirrors the original main.tsx behavior exactly: network/parse failures
 * reject (callers catch and show a generic "could not reach the API"
 * message), while HTTP-level failures (4xx/5xx) still resolve with their
 * JSON body so callers can read a server-provided `error` field themselves,
 * the same way the previous inline fetch calls did.
 */

// API layer: every request goes to the FastAPI backend (api-py) on port 8001
export const API_BASE_URL = "http://localhost:8001";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  return (await response.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function apiPost<T>(path: string, data?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: data === undefined ? undefined : { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
}
