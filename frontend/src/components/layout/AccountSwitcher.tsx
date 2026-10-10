"use client";

import { Check, ChevronsUpDown, Plus, Wallet } from "lucide-react";
import Link from "next/link";
import { ConnectionDot, EnvBadge } from "@/components/app/badges";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { formatCurrency as formatMoney } from "@/lib/format";
import { useAppData } from "../providers/AppDataProvider";

/** "Which account am I looking at, and how much is in it?" — always visible. */
export function AccountSwitcher() {
  const { accounts, account, selectAccount } = useAppData();

  if (accounts && accounts.length === 0) {
    return (
      <Link href="/settings/brokers/new" className="inline-flex h-11 min-w-0 items-center gap-2 rounded-full border border-dashed border-line-strong px-4 text-sm font-semibold text-fg-muted transition-colors hover:border-fg/50 hover:text-fg">
        <Plus className="size-4 shrink-0" aria-hidden /> <span className="truncate">Connect a broker</span>
      </Link>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={account ? `Account: ${account.label}, balance ${formatMoney(account.balance, account.currency)}. Change account` : "Choose account"}
        className="group flex h-11 w-full min-w-0 items-center gap-2.5 rounded-full bg-card py-1 pr-3 pl-1.5 text-left shadow-card ring-1 ring-line transition-[background-color,box-shadow] hover:ring-line-strong sm:w-auto sm:max-w-80 lg:bg-background dark:bg-[#1f1f1f] dark:ring-transparent dark:hover:bg-[#2a2a2a] dark:hover:ring-[#3a3a3a]"
      >
        {account ? (
          <>
            <span className="pl-1.5 sm:hidden"><ConnectionDot status={account.connection_status} /></span>
            <span className="relative hidden size-8 shrink-0 items-center justify-center rounded-full bg-surface-hover sm:flex dark:bg-[#2a2a2a]">
              <Wallet className="size-4 text-fg-muted" aria-hidden />
              <span className="absolute -right-0.5 -bottom-0.5 rounded-full bg-card p-0.5 dark:bg-[#1f1f1f]"><ConnectionDot status={account.connection_status} /></span>
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[11px] leading-tight font-semibold text-fg-muted">{account.label}</span>
              <span className="num block text-[15px] leading-tight font-bold whitespace-nowrap text-fg">{formatMoney(account.balance, account.currency)}</span>
            </span>
          </>
        ) : (
          <span className="flex-1 pl-2 text-sm text-fg-muted">Loading…</span>
        )}
        <ChevronsUpDown className="size-4 shrink-0 text-fg-subtle" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-80 max-w-[calc(100vw-2rem)]">
        <DropdownMenuLabel>Accounts</DropdownMenuLabel>
        {(accounts ?? []).map((a) => (
          <DropdownMenuItem key={a.id} onSelect={() => selectAccount(a.id)} className="gap-3 py-2">
            <ConnectionDot status={a.connection_status} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm">{a.label}</span>
              <span className="num block truncate text-xs text-fg-subtle">{formatMoney(a.balance, a.currency)} · {a.broker}</span>
            </span>
            <EnvBadge env={a.environment} />
            {a.id === account?.id && <Check className="size-4 text-brand-ink" aria-label="Selected" />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/settings/brokers/new"><Plus aria-hidden /> Add broker</Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
