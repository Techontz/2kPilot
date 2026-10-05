"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

interface Resource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => Promise<void>;
}

interface Loaded<T> {
  key: string | null;
  data: T | null;
  error: string | null;
}

/**
 * GET a resource, optionally re-fetching every `refreshMs` while the tab is
 * visible (live dashboards poll; REST stays the single source of truth).
 * Pass `null` as the path to skip fetching.
 */
export function useApi<T>(
  path: string | null,
  query?: Record<string, string | number | boolean | null | undefined>,
  refreshMs?: number,
): Resource<T> {
  const key = path === null ? null : `${path}?${JSON.stringify(query ?? {})}`;
  const [loaded, setLoaded] = useState<Loaded<T>>({ key: null, data: null, error: null });
  const latestKey = useRef(key);
  useEffect(() => {
    latestKey.current = key;
  }, [key]);

  const load = useCallback((): Promise<void> => {
    if (path === null || key === null) return Promise.resolve();
    return api<T>(path, { query }).then(
      (data) => {
        if (latestKey.current === key) setLoaded({ key, data, error: null });
      },
      (e: unknown) => {
        const message = e instanceof ApiError ? e.message : "Something went wrong.";
        if (latestKey.current === key) setLoaded((prev) => ({ key, data: prev.key === key ? prev.data : null, error: message }));
      },
    );
    // `key` already encodes path and query.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    if (key === null) return;
    const tick = () => {
      if (document.visibilityState === "visible") void load();
    };
    const first = window.setTimeout(() => void load(), 0);
    const timer = refreshMs ? window.setInterval(tick, refreshMs) : undefined;
    const onFocus = () => void load();
    if (refreshMs) window.addEventListener("focus", onFocus);
    return () => {
      window.clearTimeout(first);
      if (timer) window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [key, load, refreshMs]);

  const current = loaded.key === key;
  return {
    data: current ? loaded.data : null,
    error: current ? loaded.error : null,
    loading: key !== null && !current,
    reload: load,
  };
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
