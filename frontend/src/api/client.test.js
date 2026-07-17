import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, apiRequest } from "./client.js";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
  };
}

describe("apiRequest", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("alphapilot_api_access_token", "test-token");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("returns parsed data and sends the bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    const data = await apiRequest("/api/assets");

    expect(data).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBe("Bearer test-token");
  });

  it("throws an auth ApiError without a token", async () => {
    window.localStorage.removeItem("alphapilot_api_access_token");

    await expect(apiRequest("/api/assets")).rejects.toMatchObject({
      name: "ApiError",
      kind: "auth",
    });
  });

  it("throws an http ApiError with status and detail for failed responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: "rate limit exceeded" },
          {
            ok: false,
            status: 429,
          },
        ),
      ),
    );

    await expect(apiRequest("/api/assets")).rejects.toMatchObject({
      message: "rate limit exceeded",
      status: 429,
      code: null,
    });
  });

  it("preserves structured HTTP error codes and messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(
            { detail: { code: "migration_required", message: "migration 017 is required" } },
            { ok: false, status: 503 },
          ),
        ),
    );

    await expect(apiRequest("/api/advisory/status")).rejects.toMatchObject({
      message: "migration 017 is required",
      status: 503,
      code: "migration_required",
    });
  });

  it("retries GET requests once after a network failure (cold start)", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    const data = await apiRequest("/api/assets");

    expect(data).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry non-GET requests", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/api/assets", { method: "POST", body: "{}" })).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("calls the Toss sync endpoint as a non-retried POST request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ synced_count: 1 }));
    vi.stubGlobal("fetch", fetchMock);

    const data = await api.toss.sync();

    expect(data).toEqual({ synced_count: 1 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/toss/sync");
    expect(init.method).toBe("POST");
  });

  it("gets the read-only signal model evaluation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "collecting" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.signalModels.evaluation()).resolves.toEqual({ status: "collecting" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/signal-models/evaluation");
    expect(init.method).toBeUndefined();
  });
});
