"use client";

import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { useApi } from "@/lib/hooks";
import type { Account, TradingStatus } from "@/lib/types";

interface AppData {
  status: TradingStatus | null;
  reloadStatus: () => Promise<void>;
  accounts: Account[] | null;
  reloadAccounts: () => Promise<void>;
  /** The account the dashboard is looking at (remembered per browser). */
  account: Account | null;
  selectAccount: (id: string) => void;
  unread: number;
  reloadUnread: () => Promise<void>;
}

const AppDataContext = createContext<AppData | null>(null);
const STORAGE_KEY = "fx.account";

/** Global, polled state: robot status, accounts, selected account, unread notifications. */
export function AppDataProvider({ children }: { children: ReactNode }) {
  const status = useApi<TradingStatus>("/trading/status", undefined, 5000);
  const accounts = useApi<Account[]>("/accounts", undefined, 10000);
  const unread = useApi<{ count: number }>("/notifications/unread-count", undefined, 15000);
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
    reloadStatus: status.reload,
    accounts: accounts.data,
    reloadAccounts: accounts.reload,
    account,
    selectAccount,
    unread: unread.data?.count ?? 0,
    reloadUnread: unread.reload,
  };
  return <AppDataContext.Provider value={value}>{children}</AppDataContext.Provider>;
}

export function useAppData(): AppData {
  const value = useContext(AppDataContext);
  if (!value) throw new Error("useAppData must be used inside AppDataProvider");
  return value;
}
