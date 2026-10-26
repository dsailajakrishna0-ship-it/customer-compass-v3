import { afterEach, describe, expect, it, vi } from "vitest";
import { API_BASE_URL, apiGet, apiPost } from "./client";

function mockFetch(body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({ json: () => Promise.resolve(body) });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("GETs from the API base URL and returns the parsed JSON", async () => {
    const fetchMock = mockFetch({ ok: true });
    await expect(apiGet("/api/v1/health")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE_URL}/api/v1/health`, undefined);
  });

  it("POSTs JSON with a content-type header", async () => {
    const fetchMock = mockFetch({ id: 1 });
    await apiPost("/api/v1/things", { name: "x" });
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE_URL}/api/v1/things`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "x" }),
    });
  });

  it("POSTs without a body or header when no data is given", async () => {
    const fetchMock = mockFetch({});
    await apiPost("/api/v1/ingest");
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE_URL}/api/v1/ingest`, {
      method: "POST",
      headers: undefined,
      body: undefined,
    });
  });
});
