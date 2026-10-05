"use client";

import { Check, ChevronsUpDown, Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ConnectionDot, EnvBadge } from "@/components/ui/Misc";
import { cn } from "@/lib/cn";
import { useAppData } from "../providers/AppDataProvider";

/** "Which broker/account am I using, and is it PAPER, DEMO or LIVE?" — always visible. */
export function AccountSwitcher() {
  const { accounts, account, selectAccount } = useAppData();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  if (accounts && accounts.length === 0) {
    return (
      <Link href="/brokers/new" className="inline-flex h-9 items-center gap-2 rounded-lg border border-dashed border-line-strong px-3 text-sm text-fg-muted hover:text-fg">
        <Plus className="size-4" aria-hidden /> Connect a broker
      </Link>
    );
  }

  return (
    <div ref={ref} className="relative min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Choose account"
        className="flex h-10 w-full min-w-0 items-center gap-2 rounded-lg border border-line bg-surface px-2.5 text-left hover:border-line-strong sm:w-auto sm:gap-3 sm:px-3"
      >
        {account ? (
          <>
            <ConnectionDot status={account.connection_status} />
            <span className="min-w-0">
              <span className="block truncate text-sm leading-tight font-medium text-fg">{account.label}</span>
              <span className="block truncate text-[11px] leading-tight text-fg-subtle">
                {account.broker} · {account.broker_account_id}
              </span>
            </span>
            <EnvBadge env={account.environment} />
          </>
        ) : (
          <span className="text-sm text-fg-muted">Loading accounts…</span>
        )}
        <ChevronsUpDown className="size-4 shrink-0 text-fg-subtle" aria-hidden />
      </button>
      {open && accounts && (
        <div role="listbox" aria-label="Accounts" className="absolute top-full left-0 z-40 mt-1.5 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-line-strong bg-surface-raised p-1.5 shadow-2xl shadow-black/50">
          {accounts.map((a) => (
            <button
              key={a.id}
              type="button"
              role="option"
              aria-selected={a.id === account?.id}
              onClick={() => {
                selectAccount(a.id);
                setOpen(false);
              }}
              className={cn("flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left hover:bg-surface-hover", a.id === account?.id && "bg-surface-hover")}
            >
              <ConnectionDot status={a.connection_status} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-fg">{a.label}</span>
                <span className="block truncate text-xs text-fg-subtle">{a.broker} · {a.connection_status.toLowerCase()}</span>
              </span>
              <EnvBadge env={a.environment} />
              {a.id === account?.id && <Check className="size-4 text-accent" aria-hidden />}
            </button>
          ))}
          <Link href="/brokers/new" onClick={() => setOpen(false)} className="mt-1 flex items-center gap-2 rounded-lg border-t border-line px-2.5 pt-2.5 pb-1.5 text-sm text-fg-muted hover:text-fg">
            <Plus className="size-4" aria-hidden /> Add broker
          </Link>
        </div>
      )}
    </div>
  );
}
