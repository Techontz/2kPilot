"use client";

import { useCallback, useState } from "react";
import { ApiError } from "./api";

/** Wraps a mutating call with busy/error state. Returns the result or null on failure. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  return { run, busy, error, setError };
}
