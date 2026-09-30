"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiRequest } from "./api";

export interface ApiResource<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (data: T) => void;
}

interface Options {
  /** Refetch when the tab regains focus (default true). */
  refetchOnFocus?: boolean;
  /** Optional refresh interval in ms; keep it rare — real-time push arrives with the engine. */
  intervalMs?: number;
  enabled?: boolean;
}

export function useApiResource<T>(path: string, options: Options = {}): ApiResource<T> {
  const { refetchOnFocus = true, intervalMs, enabled = true } = options;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(enabled);
  const controller = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    controller.current?.abort();
    const ctrl = new AbortController();
    controller.current = ctrl;
    try {
      const result = await apiRequest<T>(path, { signal: ctrl.signal });
      setData(result);
      setError(null);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof ApiError ? err : new ApiError(0, "unknown", String(err)));
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    if (!enabled) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch on mount
    void reload();
    const onFocus = () => void reload();
    if (refetchOnFocus) window.addEventListener("focus", onFocus);
    const timer = intervalMs ? window.setInterval(onFocus, intervalMs) : undefined;
    return () => {
      controller.current?.abort();
      window.removeEventListener("focus", onFocus);
      if (timer) window.clearInterval(timer);
    };
  }, [enabled, intervalMs, refetchOnFocus, reload]);

  return { data, error, loading, reload, setData };
}
