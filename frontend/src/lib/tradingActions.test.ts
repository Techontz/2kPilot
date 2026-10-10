import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, ensureCsrf } from "./api";
import { resumeTrading, returnToDemo, stopTrading, withRetry } from "./tradingActions";

const api = vi.fn();
vi.mock("./api", async (orig) => ({
  ...(await orig<typeof import("./api")>()),
  api: (...args: unknown[]) => api(...args),
  ensureCsrf: vi.fn(async () => undefined),
}));

const tooMany = (retryAfter: number | null = null) => new ApiError(429, "http_error", "Too Many Attempts.", {}, [], retryAfter);
const csrfExpired = () => new ApiError(419, "http_error", "CSRF token mismatch.");

beforeEach(() => {
  api.mockReset();
  vi.mocked(ensureCsrf).mockClear();
});

describe("withRetry (STOP TRADING must get through)", () => {
  it("waits for Retry-After after a 429, then tries again", async () => {
    const sleep = vi.fn(async () => undefined);
    const call = vi.fn().mockRejectedValueOnce(tooMany(3)).mockResolvedValueOnce("ok");
    await expect(withRetry(call, { sleep })).resolves.toBe("ok");
    expect(sleep).toHaveBeenCalledWith(3000);
    expect(call).toHaveBeenCalledTimes(2);
  });

  it("caps the wait and uses a default when Retry-After is missing", async () => {
    const sleep = vi.fn(async () => undefined);
    const call = vi.fn().mockRejectedValueOnce(tooMany(600)).mockRejectedValueOnce(tooMany()).mockResolvedValueOnce("ok");
    await withRetry(call, { sleep, maxDelayMs: 10_000, fallbackDelayMs: 1000 });
    expect(sleep.mock.calls).toEqual([[10_000], [1000]]);
  });

  it("refreshes an expired CSRF token once (419), then retries", async () => {
    const call = vi.fn().mockRejectedValueOnce(csrfExpired()).mockResolvedValueOnce("ok");
    await expect(withRetry(call, { sleep: async () => undefined })).resolves.toBe("ok");
    expect(ensureCsrf).toHaveBeenCalledWith(true);
    const twice = vi.fn().mockRejectedValue(csrfExpired());
    await expect(withRetry(twice, { sleep: async () => undefined })).rejects.toMatchObject({ status: 419 });
    expect(twice).toHaveBeenCalledTimes(2);
  });

  it("retries a network failure", async () => {
    const call = vi.fn().mockRejectedValueOnce(new ApiError(0, "network_error", "Cannot reach")).mockResolvedValueOnce("ok");
    await expect(withRetry(call, { sleep: async () => undefined })).resolves.toBe("ok");
  });

  it("gives up after the last retry and on errors that retrying cannot fix", async () => {
    const limited = vi.fn().mockRejectedValue(tooMany(0));
    await expect(withRetry(limited, { maxRetries: 2, sleep: async () => undefined })).rejects.toMatchObject({ status: 429 });
    expect(limited).toHaveBeenCalledTimes(3);
    const forbidden = vi.fn().mockRejectedValue(new ApiError(403, "forbidden", "No."));
    await expect(withRetry(forbidden, { sleep: async () => undefined })).rejects.toMatchObject({ status: 403 });
    expect(forbidden).toHaveBeenCalledTimes(1);
  });

  it("stopTrading posts the reason and returns the server's status", async () => {
    api.mockRejectedValueOnce(tooMany(0)).mockResolvedValueOnce({ kill_switch_engaged: true });
    await expect(stopTrading("panic", { sleep: async () => undefined })).resolves.toEqual({ kill_switch_engaged: true });
    expect(api).toHaveBeenCalledWith("/trading/stop", { method: "POST", body: { reason: "panic" } });
  });
});

describe("resumeTrading", () => {
  it("sends the LIVE confirmation the user gave", async () => {
    api.mockResolvedValue({});
    await resumeTrading(true);
    expect(api).toHaveBeenLastCalledWith("/trading/resume", { method: "POST", body: { confirm: true, live: true } });
    await resumeTrading(false);
    expect(api).toHaveBeenLastCalledWith("/trading/resume", { method: "POST", body: { confirm: true, live: false } });
  });
});

describe("returnToDemo", () => {
  it("stops first when the server asks, and returns the final status", async () => {
    api.mockRejectedValueOnce(new ApiError(409, "stop_first", "Stop first"))
      .mockResolvedValueOnce({ kill_switch_engaged: true })
      .mockResolvedValueOnce({ trading_mode: "DEMO" });
    await expect(returnToDemo()).resolves.toEqual({ trading_mode: "DEMO" });
    expect(api.mock.calls.map((c) => c[0])).toEqual(["/trading/mode", "/trading/stop", "/trading/mode"]);
  });
});
