"use client";

import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { useApi, useHeldTrue } from "@/lib/hooks";
import { isLive } from "@/lib/live";
import type { Account, TradingStatus } from "@/lib/types";
import { useLiveEvent, useLiveState } from "./LiveProvider";

interface AppData {
  /** The trading status as last loaded. Check `statusUnknown` before trusting it. */
  status: TradingStatus | null;
  /**
   * The latest GET /trading/status failed: `status` is only the last-known
   * value. Controls show "Status unknown — reconnecting" instead of it, and
   * Stop stays available.
   */
  statusUnknown: boolean;
  statusError: string | null;
  /** Fetch the status now; resolves with the freshest status, or null if it could not be loaded. */
  reloadStatus: () => Promise<TradingStatus | null>;
  /** Show a status the server just returned (stop / resume / mode responses). */
  setStatus: (status: TradingStatus) => void;
  accounts: Account[] | null;
  reloadAccounts: () => Promise<unknown>;
  /** The account the dashboard is looking at (remembered per browser). */
  account: Account | null;
  selectAccount: (id: string) => void;
  unread: number;
  reloadUnread: () => Promise<unknown>;
  /** True while the /api/stream connection is open (polling is slowed down). */
  live: boolean;
}

const AppDataContext = createContext<AppData | null>(null);
const STORAGE_KEY = "tp.account";

/** How long the stream may be down before polling speeds up (it reconnects about once a minute by design). */
const STREAM_DOWN_GRACE_MS = 5000;

/**
 * Global state: robot status, accounts, selected account, unread notifications.
 * Pushed by the live stream when it is open (events trigger a refetch — REST
 * stays the single source of truth); polled quickly when it has been down for
 * a few seconds.
 */
export function AppDataProvider({ children }: { children: ReactNode }) {
  const live = useHeldTrue(isLive(useLiveState()), STREAM_DOWN_GRACE_MS);
  const status = useApi<TradingStatus>("/trading/status", undefined, live ? 60_000 : 5000);
  const accounts = useApi<Account[]>("/accounts", undefined, live ? 60_000 : 10_000);
  const unread = useApi<{ count: number }>("/notifications/unread-count", undefined, live ? 120_000 : 15_000);

  const reloadStatus = status.reload;
  const reloadAccounts = accounts.reload;
  const reloadUnread = unread.reload;
  useLiveEvent("trading.status", () => void reloadStatus());
  useLiveEvent("account.balance", () => void reloadAccounts());
  useLiveEvent("trade.opened", () => void reloadAccounts());
  useLiveEvent("trade.closed", () => void reloadAccounts());
  useLiveEvent("notification", () => void reloadUnread());
  // Rendered only in the browser (after the session loads), so storage is available.
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    try {
      return window.localStorage.getItem(STORAGE_KEY);
    } catch {
      return null; // storage unavailable (private mode): use the first account
    }
  });

  const selectAccount = useCallback((id: string) => {
    setSelectedId(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // ignore
    }
  }, []);

  const account = useMemo(() => {
    const list = accounts.data ?? [];
    return list.find((a) => a.id === selectedId) ?? list[0] ?? null;
  }, [accounts.data, selectedId]);

  const value: AppData = {
    status: status.data,
    statusUnknown: status.stale,
    statusError: status.error,
    reloadStatus: status.reload,
    setStatus: status.set,
    accounts: accounts.data,
    reloadAccounts: accounts.reload,
    account,
    selectAccount,
    unread: unread.data?.count ?? 0,
    reloadUnread: unread.reload,
    live,
  };
  return <AppDataContext.Provider value={value}>{children}</AppDataContext.Provider>;
}

export function useAppData(): AppData {
  const value = useContext(AppDataContext);
  if (!value) throw new Error("useAppData must be used inside AppDataProvider");
  return value;
}
