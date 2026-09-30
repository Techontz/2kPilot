"use client";

import { createContext, type ReactNode, useContext } from "react";
import type { ApiError } from "@/lib/api";
import { useLiveRefresh } from "./StreamProvider";
import type { SystemStatus, TradingStatus } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";

interface SystemStatusValue {
  status: SystemStatus | null;
  error: ApiError | null;
  reload: () => Promise<void>;
  /** Apply a trading status returned by a control action without refetching. */
  applyTradingStatus: (trading: TradingStatus) => void;
}

const SystemStatusContext = createContext<SystemStatusValue | null>(null);

// Status is pushed via the event stream; a slow 30s refresh is only a fallback
// (e.g. if the stream is interrupted by a proxy).
const STATUS_REFRESH_MS = 30_000;

export function SystemStatusProvider({ children }: { children: ReactNode }) {
  const resource = useApiResource<SystemStatus>("/system/status", { intervalMs: STATUS_REFRESH_MS });
  useLiveRefresh(["status", "broker"], () => void resource.reload(), 1500);

  const value: SystemStatusValue = {
    status: resource.data,
    error: resource.error,
    reload: resource.reload,
    applyTradingStatus: (trading) => {
      if (resource.data) resource.setData({ ...resource.data, trading });
    },
  };
  return <SystemStatusContext.Provider value={value}>{children}</SystemStatusContext.Provider>;
}

export function useSystemStatus(): SystemStatusValue {
  const ctx = useContext(SystemStatusContext);
  if (!ctx) throw new Error("useSystemStatus must be used inside SystemStatusProvider");
  return ctx;
}
