import { api, ApiError, ensureCsrf } from "./api";
import type { TradingStatus } from "./types";

/**
 * The trading controls' requests. Each returns the full trading status the
 * server answers with, so the dashboard can show it at once (no refetch,
 * no moment where the old state is still on screen).
 */

export interface RetryOptions {
  /** Retries after a 429 (rate limited) or a network failure. */
  maxRetries?: number;
  /** Wait used when a 429 has no Retry-After (and after a network failure). */
  fallbackDelayMs?: number;
  /** Never wait longer than this between tries. */
  maxDelayMs?: number;
  sleep?: (ms: number) => Promise<void>;
}

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Run a request that must get through (STOP TRADING): a 429 waits for
 * Retry-After and tries again, an expired CSRF token (419) is refreshed once,
 * a network failure is retried. Anything else — or running out of tries —
 * throws the last error.
 */
export async function withRetry<T>(call: () => Promise<T>, options: RetryOptions = {}): Promise<T> {
  const { maxRetries = 3, fallbackDelayMs = 1000, maxDelayMs = 10_000, sleep = wait } = options;
  let retries = 0;
  let csrfRefreshed = false;
  for (;;) {
    try {
      return await call();
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      if (error.status === 419 && !csrfRefreshed) {
        csrfRefreshed = true;
        await ensureCsrf(true);
        continue;
      }
      if ((error.status === 429 || error.status === 0) && retries < maxRetries) {
        retries += 1;
        const delay = error.retryAfter !== null ? error.retryAfter * 1000 : fallbackDelayMs;
        await sleep(Math.min(maxDelayMs, Math.max(250, delay)));
        continue;
      }
      throw error;
    }
  }
}

/** STOP TRADING — always allowed, retried until it gets through (or clearly fails). */
export function stopTrading(reason: string, options?: RetryOptions): Promise<TradingStatus> {
  return withRetry(() => api<TradingStatus>("/trading/stop", { method: "POST", body: { reason } }), options);
}

/**
 * Start trading. `live` says the user confirmed the LIVE (real-money)
 * wording; the server refuses to start LIVE without it
 * (code `live_confirmation_required`).
 */
export function resumeTrading(live: boolean): Promise<TradingStatus> {
  return api<TradingStatus>("/trading/resume", { method: "POST", body: { confirm: true, live } });
}

/**
 * Leave LIVE in one click. The mode can only change while trading is
 * stopped, so this stops trading first when needed (always safe), then
 * switches to DEMO. Returns the new status.
 */
export async function returnToDemo(): Promise<TradingStatus> {
  try {
    return await api<TradingStatus>("/trading/mode", { method: "PUT", body: { mode: "DEMO" } });
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "stop_first") throw error;
    await stopTrading("Returning to Demo");
    return api<TradingStatus>("/trading/mode", { method: "PUT", body: { mode: "DEMO" } });
  }
}
