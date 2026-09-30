"use client";

import { useState } from "react";
import type { TradingAccount } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";

const NONE: TradingAccount[] = [];

/** Accounts list plus a selected account. Without `allowAll`, defaults to the first account. */
export function useAccounts(options: { allowAll?: boolean } = {}) {
  const resource = useApiResource<TradingAccount[]>("/accounts");
  const [chosen, setSelected] = useState<string | null>(null);
  const accounts = resource.data ?? NONE;
  const selected = chosen ?? (options.allowAll ? null : (accounts[0]?.id ?? null));
  const current = accounts.find((a) => a.id === selected) ?? null;
  return { ...resource, accounts, selected, setSelected, current };
}
