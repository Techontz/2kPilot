import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiRequest, readCookie, setUnauthorizedHandler } from "./api";

const fetchMock = vi.fn();

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "fx_csrf=csrf-token-123";
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
  setUnauthorizedHandler(null);
});

describe("apiRequest", () => {
  it("sends the CSRF token on mutations only", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await apiRequest("/trading/stop", { method: "POST", body: {} });
    await apiRequest("/system/status");
    const [, postInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const [, getInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect((postInit.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-token-123");
    expect((getInit.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/trading/stop");
  });

  it("maps the backend error envelope to ApiError", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(409, { error: { code: "conflict", message: "Stop first", correlation_id: "cid" } }),
    );
    const error = await apiRequest("/trading/mode", { method: "PUT", body: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "conflict", message: "Stop first", correlationId: "cid" });
  });

  it("reports network failures clearly", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    await expect(apiRequest("/system/status")).rejects.toMatchObject({ code: "network_error", status: 0 });
  });

  it("calls the unauthorized handler on 401, except for login", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    fetchMock.mockResolvedValue(jsonResponse(401, { error: { code: "not_authenticated", message: "no" } }));
    await apiRequest("/auth/me").catch(() => undefined);
    await apiRequest("/auth/login", { method: "POST", body: {} }).catch(() => undefined);
    expect(handler).toHaveBeenCalledTimes(1);
  });
});

describe("readCookie", () => {
  it("parses cookies", () => {
    expect(readCookie("b", "a=1; b=two%20words; c=3")).toBe("two words");
    expect(readCookie("missing", "a=1")).toBeNull();
  });
});
