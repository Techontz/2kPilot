import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { useApi, useHeldTrue } from "./hooks";

const api = vi.fn();
vi.mock("./api", async (orig) => ({ ...(await orig<typeof import("./api")>()), api: (...args: unknown[]) => api(...args) }));

/** A request the test answers by hand, in any order. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => api.mockReset());
afterEach(() => vi.useRealTimers());

describe("useApi request sequencing", () => {
  it("never lets an older response overwrite a newer one", async () => {
    const first = deferred<{ mode: string }>();
    const second = deferred<{ mode: string }>();
    api.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => useApi<{ mode: string }>("/trading/status"));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(1)); // the first load
    let newest: Promise<{ mode: string } | null> = Promise.resolve(null);
    act(() => {
      newest = result.current.reload();
    });
    await act(async () => second.resolve({ mode: "LIVE" }));
    expect(result.current.data).toEqual({ mode: "LIVE" });
    await act(async () => first.resolve({ mode: "DEMO" })); // late, out of order: dropped
    expect(result.current.data).toEqual({ mode: "LIVE" });
    await expect(newest).resolves.toEqual({ mode: "LIVE" });
  });

  it("answers a superseded reload with the newest value", async () => {
    const first = deferred<{ n: number }>();
    const second = deferred<{ n: number }>();
    api.mockResolvedValueOnce({ n: 0 }).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => useApi<{ n: number }>("/x"));
    await waitFor(() => expect(result.current.data).toEqual({ n: 0 }));
    let older: Promise<{ n: number } | null> = Promise.resolve(null);
    act(() => {
      older = result.current.reload();
      void result.current.reload();
    });
    await act(async () => {
      first.resolve({ n: 1 });
      second.resolve({ n: 2 });
    });
    await expect(older).resolves.toEqual({ n: 2 });
    expect(result.current.data).toEqual({ n: 2 });
  });

  it("marks the data stale (last known) when the latest request fails, and recovers", async () => {
    api.mockResolvedValueOnce({ mode: "DEMO" });
    const { result } = renderHook(() => useApi<{ mode: string }>("/trading/status"));
    await waitFor(() => expect(result.current.data).toEqual({ mode: "DEMO" }));
    expect(result.current.stale).toBe(false);
    api.mockRejectedValueOnce(new ApiError(0, "network_error", "Cannot reach the 2kPilot server."));
    let answer: { mode: string } | null = { mode: "?" };
    await act(async () => {
      answer = await result.current.reload();
    });
    expect(answer).toBeNull();
    expect(result.current.stale).toBe(true);
    expect(result.current.error).toMatch(/Cannot reach/);
    expect(result.current.data).toEqual({ mode: "DEMO" }); // kept, but flagged
    api.mockResolvedValueOnce({ mode: "DEMO" });
    await act(async () => {
      await result.current.reload();
    });
    expect(result.current.stale).toBe(false);
  });

  it("an older failure cannot mark newer data stale", async () => {
    const slow = deferred<{ n: number }>();
    api.mockResolvedValueOnce({ n: 0 }).mockReturnValueOnce(slow.promise).mockResolvedValueOnce({ n: 2 });
    const { result } = renderHook(() => useApi<{ n: number }>("/x"));
    await waitFor(() => expect(result.current.data).toEqual({ n: 0 }));
    await act(async () => {
      void result.current.reload();
      await result.current.reload();
    });
    await act(async () => slow.reject(new ApiError(500, "http_error", "boom")));
    expect(result.current.data).toEqual({ n: 2 });
    expect(result.current.stale).toBe(false);
  });

  it("set() shows a server answer at once and drops requests still in flight", async () => {
    const inFlight = deferred<{ mode: string }>();
    api.mockResolvedValueOnce({ mode: "DEMO" }).mockReturnValueOnce(inFlight.promise);
    const { result } = renderHook(() => useApi<{ mode: string }>("/trading/status"));
    await waitFor(() => expect(result.current.data).toEqual({ mode: "DEMO" }));
    act(() => {
      void result.current.reload(); // started before the mutation answered
      result.current.set({ mode: "LIVE" });
    });
    expect(result.current.data).toEqual({ mode: "LIVE" });
    await act(async () => inFlight.resolve({ mode: "DEMO" }));
    expect(result.current.data).toEqual({ mode: "LIVE" });
  });

  it("does not fetch immediately when only the polling interval changes", async () => {
    vi.useFakeTimers();
    api.mockResolvedValue({ ok: true });
    const { rerender } = renderHook(({ ms }) => useApi("/x", undefined, ms), { initialProps: { ms: 5000 } });
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(api).toHaveBeenCalledTimes(1);
    rerender({ ms: 60_000 }); // the stream came back: slower polling
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(api).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(api).toHaveBeenCalledTimes(2);
  });
});

describe("useHeldTrue", () => {
  it("turns on at once but only turns off after the hold time", async () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ v }) => useHeldTrue(v, 5000), { initialProps: { v: true } });
    expect(result.current).toBe(true);
    rerender({ v: false }); // the stream's planned reconnect
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(result.current).toBe(true);
    rerender({ v: true }); // back within the grace period: never flipped
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(result.current).toBe(true);
    rerender({ v: false });
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(result.current).toBe(false);
  });
});
