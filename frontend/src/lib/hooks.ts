"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

interface Resource<T> {
  data: T | null;
  error: string | null;
  /** The last request failed: `data` (if any) is the last value that loaded, not the current one. */
  stale: boolean;
  loading: boolean;
  /** Fetch now. Resolves with the freshest value, or null when it could not be loaded. */
  reload: () => Promise<T | null>;
  /** Use a value the server just returned (e.g. a mutation's response); older in-flight requests are dropped. */
  set: (data: T) => void;
}

const FAILING_REFRESH_MS = 5000;

interface Loaded<T> {
  key: string | null;
  data: T | null;
  error: string | null;
}

/**
 * GET a resource, optionally re-fetching every `refreshMs` while the tab is
 * visible (live dashboards poll; REST stays the single source of truth).
 * Pass `null` as the path to skip fetching.
 *
 * Requests are sequenced: only the newest request's answer (or failure) is
 * applied, so a slow old response can never overwrite a newer one.
 */
export function useApi<T>(
  path: string | null,
  query?: Record<string, string | number | boolean | null | undefined>,
  refreshMs?: number,
): Resource<T> {
  const key = path === null ? null : `${path}?${JSON.stringify(query ?? {})}`;
  const [loaded, setLoaded] = useState<Loaded<T>>({ key: null, data: null, error: null });
  const latestKey = useRef(key);
  const seq = useRef(0);
  const newest = useRef<Promise<T | null>>(Promise.resolve(null));
  useEffect(() => {
    latestKey.current = key;
  }, [key]);

  const load = useCallback((): Promise<T | null> => {
    if (path === null || key === null) return Promise.resolve(null);
    const mine = ++seq.current;
    // Superseded (a newer request or value came first): answer with the newest instead.
    const superseded = () => (latestKey.current === key ? newest.current : Promise.resolve(null));
    const request = api<T>(path, { query }).then(
      (data): Promise<T | null> | T | null => {
        if (mine !== seq.current || latestKey.current !== key) return superseded();
        setLoaded({ key, data, error: null });
        return data;
      },
      (e: unknown): Promise<T | null> | null => {
        if (mine !== seq.current || latestKey.current !== key) return superseded();
        const message = e instanceof ApiError ? e.message : "Something went wrong.";
        setLoaded((prev) => ({ key, data: prev.key === key ? prev.data : null, error: message }));
        return null;
      },
    );
    newest.current = request;
    return request;
    // `key` already encodes path and query.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const set = useCallback(
    (data: T) => {
      if (key === null) return;
      seq.current += 1; // anything still in flight is older than this value
      newest.current = Promise.resolve(data);
      setLoaded({ key, data, error: null });
    },
    [key],
  );

  // First load when the resource changes (not when only the polling interval does).
  useEffect(() => {
    if (key === null) return;
    const first = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(first);
  }, [key, load]);

  // While the last request failed, poll at least every 5 s so it recovers quickly.
  const failing = loaded.key === key && loaded.error !== null;
  const interval = refreshMs && failing ? Math.min(refreshMs, FAILING_REFRESH_MS) : refreshMs;
  useEffect(() => {
    if (key === null || !interval) return;
    const tick = () => {
      if (document.visibilityState === "visible") void load();
    };
    const timer = window.setInterval(tick, interval);
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [key, load, interval]);

  const current = loaded.key === key;
  return {
    data: current ? loaded.data : null,
    error: current ? loaded.error : null,
    stale: current && loaded.error !== null,
    loading: key !== null && !current,
    reload: load,
    set,
  };
}

/**
 * `value`, but a change to false only shows after `holdMs` (a change to true
 * shows at once). Keeps brief dips — the live stream's planned reconnect
 * about once a minute — from flipping the dashboard into fast polling.
 */
export function useHeldTrue(value: boolean, holdMs: number): boolean {
  const [held, setHeld] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setHeld(value), value ? 0 : holdMs);
    return () => window.clearTimeout(timer);
  }, [value, holdMs]);
  return value || held;
}

/** Run a mutation with busy/error state. Returns the result, or null on failure. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});

  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      return await fn();
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.message);
        setFieldErrors(e.fieldErrors);
      } else {
        setError("Something went wrong.");
      }
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const reset = useCallback(() => {
    setError(null);
    setFieldErrors({});
  }, []);

  return { busy, error, fieldErrors, run, reset };
}

/** The current time, re-rendered every `intervalMs` while `enabled` (for countdowns). */
export function useNow(intervalMs = 1000, enabled = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs, enabled]);
  return now;
}
