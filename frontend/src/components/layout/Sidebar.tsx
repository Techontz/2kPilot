"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { EnvBadge } from "@/components/app/badges";
import { formatCurrency } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useAppData } from "../providers/AppDataProvider";
import { isActive, NAVIGATION } from "./nav";

/**
 * Desktop navigation as two stacked rounded panels: the four sections on top,
 * and "Your accounts" below (wide screens) — a library of the accounts you can
 * switch between. Compact icon rail on smaller desktops.
 */
export function Sidebar() {
  const pathname = usePathname();
  return (
    <div className="flex h-full flex-col gap-2">
      <nav aria-label="Main" className="rounded-lg bg-background px-2 py-3 xl:px-3">
        <ul className="flex flex-col gap-1">
          {NAVIGATION.map(({ href, label, icon: Icon }) => {
            const active = isActive(pathname, href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group relative flex flex-col items-center gap-1 rounded-md px-2 py-2 text-[11px] font-semibold transition-colors xl:flex-row xl:gap-4 xl:px-3 xl:py-2.5 xl:text-[15px] xl:font-bold",
                    active ? "bg-surface-hover text-fg" : "text-fg-muted hover:text-fg",
                  )}
                >
                  {active && <span aria-hidden className="absolute top-1/2 left-0 h-5 w-1 -translate-y-1/2 rounded-full bg-primary xl:-left-1" />}
                  <Icon aria-hidden className={cn("size-5 shrink-0 transition-transform group-hover:scale-105 xl:size-6", active && "text-brand-ink")} strokeWidth={active ? 2.4 : 2} />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <AccountsLibrary />
    </div>
  );
}

function AccountsLibrary() {
  const { accounts, account, selectAccount } = useAppData();
  return (
    <section aria-labelledby="library-title" className="hidden min-h-0 flex-1 flex-col rounded-lg bg-background xl:flex">
      <div className="flex items-center justify-between px-5 pt-4 pb-2">
        <h2 id="library-title" className="text-[15px] font-bold text-fg-muted">Your accounts</h2>
        <Link href="/settings/brokers/new" aria-label="Add broker account" title="Add broker account"
          className="flex size-8 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg">
          <Plus className="size-4" aria-hidden />
        </Link>
      </div>
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {(accounts ?? []).map((a) => {
          const selected = a.id === account?.id;
          return (
            <li key={a.id}>
              <button type="button" onClick={() => selectAccount(a.id)} aria-pressed={selected}
                className={cn("flex w-full items-center gap-3 rounded-md p-2 text-left transition-colors hover:bg-surface-hover", selected && "bg-surface-hover")}>
                <span aria-hidden className={cn("flex size-11 shrink-0 items-center justify-center rounded-md text-sm font-extrabold",
                  a.environment === "LIVE" ? "bg-live text-live-foreground" : a.environment === "DEMO" ? "bg-demo-soft text-demo" : "bg-muted text-fg-muted")}>
                  {a.label.slice(0, 1).toUpperCase()}
                </span>
                <span className="min-w-0 flex-1">
                  <span className={cn("block truncate text-sm font-semibold", selected ? "text-brand-ink" : "text-fg")}>{a.label}</span>
                  <span className="mt-0.5 flex items-center gap-1.5 text-xs text-fg-muted">
                    <EnvBadge env={a.environment} className="h-4 px-1.5 text-[10px]" />
                    <span className="num truncate">{formatCurrency(a.balance, a.currency)}</span>
                  </span>
                </span>
              </button>
            </li>
          );
        })}
        {accounts && accounts.length === 0 && (
          <li className="rounded-md bg-surface-raised p-4">
            <p className="text-sm font-bold text-fg">Add your first account</p>
            <p className="mt-1 text-xs text-fg-muted">Start with Paper — simulated money, no sign-up.</p>
            <Link href="/settings/brokers/new" className="mt-3 inline-flex h-8 items-center rounded-full bg-foreground px-4 text-xs font-bold text-background transition-transform hover:scale-[1.03]">Add account</Link>
          </li>
        )}
      </ul>
      <p className="border-t border-line px-5 py-3 text-[11px] leading-relaxed text-fg-subtle">Every trade passes your risk limits. Stop is always one click.</p>
    </section>
  );
}
